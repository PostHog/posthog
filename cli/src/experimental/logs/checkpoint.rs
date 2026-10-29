use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};

/// Progress through a run, written after each shard is fully acknowledged.
///
/// The unit is a whole shard because the intake assigns record ids at ingest and `logs34` does not
/// deduplicate, so a resumed run cannot avoid re-sending the shard it was in the middle of. Keeping
/// the unit small bounds that duplication to one shard of one selector.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct Checkpoint {
    /// The range this progress was built under. A high-water mark alone cannot tell that the
    /// operator widened `range.from`, so a rerun would produce no windows and report success
    /// without importing the newly requested history.
    #[serde(default)]
    range: Option<(i64, i64)>,
    /// Selector to the exclusive end of the last shard completed for it, as a nanosecond epoch.
    #[serde(default)]
    completed_through: BTreeMap<String, i64>,
    #[serde(default)]
    pub records_sent: u64,
    #[serde(default)]
    pub bytes_sent: u64,
}

impl Checkpoint {
    pub fn load(path: &Path) -> Result<Self> {
        match std::fs::read_to_string(path) {
            Ok(contents) => serde_json::from_str(&contents)
                .with_context(|| format!("checkpoint at {} is not readable", path.display())),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(Self::default()),
            Err(error) => Err(error).with_context(|| format!("cannot read {}", path.display())),
        }
    }

    /// Writes through a temporary file in the same directory, so a process killed mid-write leaves
    /// the previous checkpoint intact rather than a truncated one.
    pub fn save(&self, path: &Path) -> Result<()> {
        let parent = path.parent().unwrap_or(Path::new("."));
        std::fs::create_dir_all(parent)
            .with_context(|| format!("cannot create {}", parent.display()))?;

        let temporary: PathBuf = path.with_extension("tmp");
        let encoded = serde_json::to_vec_pretty(self).context("cannot encode the checkpoint")?;
        std::fs::write(&temporary, encoded)
            .with_context(|| format!("cannot write {}", temporary.display()))?;
        std::fs::rename(&temporary, path)
            .with_context(|| format!("cannot move the checkpoint into {}", path.display()))
    }

    /// Discards progress when the configured range starts earlier than the one it was built for,
    /// so widening a range re-imports the part that was never covered rather than silently doing
    /// nothing. A range that only moved its end forward keeps its progress.
    pub fn reconcile_range(&mut self, from_ns: i64, to_ns: i64) -> bool {
        match self.range {
            Some((previous_from, _)) if previous_from <= from_ns => {
                self.range = Some((previous_from.min(from_ns), to_ns));
                false
            }
            Some(_) => {
                self.completed_through.clear();
                self.range = Some((from_ns, to_ns));
                true
            }
            None => {
                self.range = Some((from_ns, to_ns));
                false
            }
        }
    }

    /// The shard a selector should resume from, or `None` when it has never run.
    pub fn resume_from(&self, selector: &str) -> Option<i64> {
        self.completed_through.get(selector).copied()
    }

    /// A shard is only recorded once every record in it is acknowledged. Recording it earlier would
    /// skip data on resume, which is worse than the duplication the shard unit already accepts.
    pub fn complete_shard(&mut self, selector: &str, shard_end_ns: i64, records: u64, bytes: u64) {
        let entry = self
            .completed_through
            .entry(selector.to_string())
            .or_insert(shard_end_ns);
        *entry = (*entry).max(shard_end_ns);
        self.records_sent += records;
        self.bytes_sent += bytes;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A unique directory per call, removed when the guard drops. Callers hold the guard so the
    /// directory outlives the path they use.
    fn temp_path(name: &str) -> (tempfile::TempDir, PathBuf) {
        let dir = tempfile::TempDir::new().expect("temp dir");
        let path = dir.path().join(name);
        (dir, path)
    }

    #[test]
    fn a_missing_checkpoint_starts_a_run_rather_than_failing_it() {
        let (_guard, path) = temp_path("does-not-exist.json");
        let loaded = Checkpoint::load(&path).expect("starts clean");

        assert_eq!(loaded, Checkpoint::default());
        assert_eq!(loaded.resume_from("{app=\"api\"}"), None);
    }

    #[test]
    fn a_saved_checkpoint_resumes_each_selector_independently() {
        let (_guard, path) = temp_path("two-selectors.json");
        let mut checkpoint = Checkpoint::default();
        checkpoint.complete_shard("{app=\"api\"}", 200, 10, 1000);
        checkpoint.complete_shard("{app=\"web\"}", 500, 5, 500);
        checkpoint.save(&path).expect("saves");

        let loaded = Checkpoint::load(&path).expect("loads");

        assert_eq!(loaded.resume_from("{app=\"api\"}"), Some(200));
        assert_eq!(loaded.resume_from("{app=\"web\"}"), Some(500));
        assert_eq!(loaded.records_sent, 15);
    }

    #[test]
    fn a_shard_completed_out_of_order_never_moves_progress_backwards() {
        // Shards run concurrently, so an earlier one can finish after a later one. Taking the
        // lower value would re-send everything between them on resume.
        let mut checkpoint = Checkpoint::default();

        checkpoint.complete_shard("{app=\"api\"}", 900, 1, 1);
        checkpoint.complete_shard("{app=\"api\"}", 300, 1, 1);

        assert_eq!(checkpoint.resume_from("{app=\"api\"}"), Some(900));
    }

    #[test]
    fn widening_the_range_discards_progress_instead_of_importing_nothing() {
        // The high-water mark alone would make shards() produce no windows, so the rerun would
        // report success without importing the newly requested history.
        let mut checkpoint = Checkpoint::default();
        checkpoint.reconcile_range(100, 500);
        checkpoint.complete_shard("{app=\"api\"}", 500, 10, 10);

        let discarded = checkpoint.reconcile_range(50, 500);

        assert!(discarded, "an earlier start must reset progress");
        assert_eq!(checkpoint.resume_from("{app=\"api\"}"), None);
    }

    #[test]
    fn extending_the_range_forward_keeps_progress() {
        let mut checkpoint = Checkpoint::default();
        checkpoint.reconcile_range(100, 500);
        checkpoint.complete_shard("{app=\"api\"}", 500, 10, 10);

        let discarded = checkpoint.reconcile_range(100, 900);

        assert!(!discarded, "a later end must not replay what is done");
        assert_eq!(checkpoint.resume_from("{app=\"api\"}"), Some(500));
    }

    #[test]
    fn a_truncated_checkpoint_is_reported_rather_than_silently_restarting() {
        // Silently starting over would re-import months of data without saying so.
        let (_guard, path) = temp_path("truncated.json");
        std::fs::write(&path, b"{\"completed_through\": {").expect("writes");

        let error = Checkpoint::load(&path).expect_err("must not be treated as a fresh run");

        assert!(format!("{error:#}").contains("not readable"));
    }

    #[test]
    fn saving_replaces_the_previous_checkpoint_atomically() {
        let (_guard, path) = temp_path("atomic.json");
        let mut first = Checkpoint::default();
        first.complete_shard("{app=\"api\"}", 100, 1, 1);
        first.save(&path).expect("first save");

        let mut second = Checkpoint::default();
        second.complete_shard("{app=\"api\"}", 400, 2, 2);
        second.save(&path).expect("second save");

        assert_eq!(
            Checkpoint::load(&path)
                .unwrap()
                .resume_from("{app=\"api\"}"),
            Some(400)
        );
        assert!(
            !path.with_extension("tmp").exists(),
            "the temporary file must be moved, not left"
        );
    }
}
