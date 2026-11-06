pub mod async_helpers;
pub mod timestamp;

use std::path::{Path, PathBuf};

/// Build the store path for a partition: `<base_path>/<topic>/<partition>/`
///
/// Replaces `/` in topic names with `_` to guarantee a two-level directory
/// structure. Both `cleanup_unowned_partition_directories` and
/// `cleanup_orphaned_directories` assume exactly `<base>/<topic>/<partition>/`.
pub fn format_store_path(base_path: &Path, topic: &str, partition: i32) -> PathBuf {
    base_path
        .join(topic.replace('/', "_"))
        .join(partition.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_format_store_path() {
        let base = Path::new("/data/stores");
        let path = format_store_path(base, "events", 5);
        assert_eq!(path, PathBuf::from("/data/stores/events/5"));
    }

    #[test]
    fn test_format_store_path_with_slashes() {
        let base = Path::new("/data/stores");
        let path = format_store_path(base, "org/events", 0);
        // Slashes are replaced with underscores to keep a two-level directory structure
        assert_eq!(path, PathBuf::from("/data/stores/org_events/0"));
    }
}
