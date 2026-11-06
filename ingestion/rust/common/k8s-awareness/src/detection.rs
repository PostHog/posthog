use crate::types::{ClusterIntent, DepartureReason};

/// Classify why a member is departing based on its controller's current intent
/// and the member's generation hash.
///
/// Logic:
/// 1. If a rollout is in progress and the member's generation doesn't match
///    the target generation, the member is being replaced.
/// 2. If desired_replicas < previous_replicas, the fleet is shrinking.
/// 3. Otherwise, assume crash (etcd lease TTL handles recovery).
pub fn classify_departure(intent: &ClusterIntent, member_generation: &str) -> DepartureReason {
    // Rollout in progress: member is old-gen if it doesn't match the target
    if intent.rollout_in_progress {
        if let Some(target) = &intent.target_generation {
            if member_generation != target {
                return DepartureReason::Rollout;
            }
        }
    }

    // Rollout completed: member is old-gen if it doesn't match the current generation.
    // This catches the case where a rollout finishes faster than our polling interval
    // but old-gen pods are still departing.
    if !intent.rollout_in_progress
        && !intent.current_generation.is_empty()
        && member_generation != intent.current_generation
    {
        return DepartureReason::Rollout;
    }

    // Downscale: desired replicas decreased
    if let Some(previous) = intent.previous_replicas {
        if intent.desired_replicas < previous {
            return DepartureReason::Downscale;
        }
    }

    // Default: crash or unknown disruption
    DepartureReason::Crash
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

    fn intent(
        desired: u32,
        previous: Option<u32>,
        rollout: bool,
        current_gen: &str,
        target_gen: Option<&str>,
    ) -> ClusterIntent {
        ClusterIntent {
            desired_replicas: desired,
            previous_replicas: previous,
            rollout_in_progress: rollout,
            current_generation: current_gen.to_string(),
            target_generation: target_gen.map(String::from),
        }
    }

    #[rstest]
    // Rollout scenarios
    #[case::rollout_old_gen_member(
        3,
        None,
        true,
        "abc123",
        Some("def456"),
        "abc123",
        DepartureReason::Rollout
    )]
    #[case::rollout_new_gen_member_is_crash(
        3,
        None,
        true,
        "abc123",
        Some("def456"),
        "def456",
        DepartureReason::Crash
    )]
    #[case::rollout_without_target_gen_is_crash(
        3,
        None,
        true,
        "abc123",
        None,
        "abc123",
        DepartureReason::Crash
    )]
    #[case::completed_rollout_old_gen_member(
        3,
        Some(3),
        false,
        "new_hash",
        None,
        "old_hash",
        DepartureReason::Rollout
    )]
    #[case::completed_rollout_current_gen_is_crash(
        3,
        Some(3),
        false,
        "new_hash",
        None,
        "new_hash",
        DepartureReason::Crash
    )]
    // Downscale scenarios
    #[case::downscale(
        2,
        Some(3),
        false,
        "abc123",
        None,
        "abc123",
        DepartureReason::Downscale
    )]
    #[case::downscale_during_rollout_prefers_rollout_for_old_gen(
        2,
        Some(3),
        true,
        "abc123",
        Some("def456"),
        "abc123",
        DepartureReason::Rollout
    )]
    #[case::downscale_during_rollout_new_gen_member(
        2,
        Some(3),
        true,
        "abc123",
        Some("def456"),
        "def456",
        DepartureReason::Downscale
    )]
    // Crash scenarios
    #[case::crash_steady_state(3, Some(3), false, "abc123", None, "abc123", DepartureReason::Crash)]
    #[case::crash_no_previous_replicas(
        3,
        None,
        false,
        "abc123",
        None,
        "abc123",
        DepartureReason::Crash
    )]
    #[case::scale_up_is_crash(5, Some(3), false, "abc123", None, "abc123", DepartureReason::Crash)]
    fn classify(
        #[case] desired: u32,
        #[case] previous: Option<u32>,
        #[case] rollout: bool,
        #[case] current_gen: &str,
        #[case] target_gen: Option<&str>,
        #[case] member_gen: &str,
        #[case] expected: DepartureReason,
    ) {
        let i = intent(desired, previous, rollout, current_gen, target_gen);
        assert_eq!(classify_departure(&i, member_gen), expected);
    }
}
