use chrono::{DateTime, Duration, Utc};

/// A half-open window `[start, end)` that one `query_range` call covers.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Shard {
    pub start: DateTime<Utc>,
    pub end: DateTime<Utc>,
}

/// Splits a range into windows, resuming past what a checkpoint already completed.
///
/// Windows are half-open so the boundary record belongs to exactly one shard. Closing both ends
/// would re-send one record per boundary, which across 13,000 shards is 13,000 duplicates.
pub fn shards(
    from: DateTime<Utc>,
    to: DateTime<Utc>,
    width_seconds: u64,
    resume_from_ns: Option<i64>,
) -> Vec<Shard> {
    let width = Duration::seconds(width_seconds.max(1) as i64);

    let mut start = match resume_from_ns.map(DateTime::from_timestamp_nanos) {
        // A checkpoint past the configured range means the range shrank since the last run.
        Some(resume) if resume >= to => return Vec::new(),
        Some(resume) if resume > from => resume,
        _ => from,
    };

    let mut windows = Vec::new();
    while start < to {
        let end = (start + width).min(to);
        windows.push(Shard { start, end });
        start = end;
    }
    windows
}

#[cfg(test)]
mod tests {
    use super::*;

    fn at(day: u32, hour: u32) -> DateTime<Utc> {
        DateTime::parse_from_rfc3339(&format!("2025-03-{day:02}T{hour:02}:00:00Z"))
            .expect("valid")
            .with_timezone(&Utc)
    }

    #[test]
    fn windows_are_half_open_and_cover_the_range_exactly_once() {
        let windows = shards(at(1, 0), at(1, 6), 3600 * 2, None);

        assert_eq!(windows.len(), 3);
        assert_eq!(windows[0].end, windows[1].start, "no gap and no overlap");
        assert_eq!(windows[2].end, at(1, 6));
    }

    #[test]
    fn a_partial_final_window_still_runs() {
        // 5 hours at a 2h shard is 2 full windows and a 1h tail. Dropping the tail silently
        // skips the end of the range.
        let windows = shards(at(1, 0), at(1, 5), 3600 * 2, None);

        assert_eq!(windows.len(), 3);
        assert_eq!(windows[2].start, at(1, 4));
        assert_eq!(windows[2].end, at(1, 5));
    }

    #[test]
    fn a_checkpoint_resumes_without_replaying_completed_windows() {
        let resume = at(1, 4).timestamp_nanos_opt().expect("in range");

        let windows = shards(at(1, 0), at(1, 8), 3600 * 2, Some(resume));

        assert_eq!(windows.len(), 2);
        assert_eq!(
            windows[0].start,
            at(1, 4),
            "must not replay the first four hours"
        );
    }

    #[test]
    fn a_checkpoint_past_the_range_produces_no_work() {
        // The range shrank since the last run. Returning windows would re-import data the
        // checkpoint says is already done.
        let resume = at(2, 0).timestamp_nanos_opt().expect("in range");

        assert!(shards(at(1, 0), at(1, 8), 3600, Some(resume)).is_empty());
    }

    #[test]
    fn a_checkpoint_before_the_range_does_not_widen_it() {
        let resume = at(1, 0).timestamp_nanos_opt().expect("in range");

        let windows = shards(at(1, 4), at(1, 8), 3600 * 2, Some(resume));

        assert_eq!(
            windows[0].start,
            at(1, 4),
            "the config bounds the run, not the checkpoint"
        );
    }
}
