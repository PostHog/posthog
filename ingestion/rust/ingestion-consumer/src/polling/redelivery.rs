use std::collections::HashMap;

use common_kafka_consumer::{Offset, TopicPartition};

/// librdkafka can repeat a partition's last message; see the README, "Polling".
#[derive(Default)]
pub(super) struct RedeliveryFilter {
    last_offsets: HashMap<TopicPartition, Offset>,
}

impl RedeliveryFilter {
    pub(super) fn admit(&mut self, topic_partition: &TopicPartition, offset: Offset) -> bool {
        match self.last_offsets.get_mut(topic_partition) {
            Some(last) if *last == offset => false,
            Some(last) => {
                *last = offset;
                true
            }
            None => {
                self.last_offsets.insert(topic_partition.clone(), offset);
                true
            }
        }
    }

    pub(super) fn forget(&mut self, topic_partition: &TopicPartition) {
        self.last_offsets.remove(topic_partition);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tp(topic: &str, partition: i32) -> TopicPartition {
        TopicPartition::new(topic, partition)
    }

    fn admitted(filter: &mut RedeliveryFilter, deliveries: &[(i32, i64)]) -> Vec<bool> {
        deliveries
            .iter()
            .map(|&(partition, offset)| filter.admit(&tp("events", partition), Offset(offset)))
            .collect()
    }

    #[test]
    fn a_partitions_first_offset_is_admitted() {
        let mut filter = RedeliveryFilter::default();
        assert_eq!(admitted(&mut filter, &[(0, 5)]), [true]);
    }

    #[test]
    fn consecutive_offsets_are_admitted() {
        let mut filter = RedeliveryFilter::default();
        assert_eq!(
            admitted(&mut filter, &[(0, 5), (0, 6), (0, 7)]),
            [true, true, true]
        );
    }

    #[test]
    fn a_repeat_of_the_last_offset_is_dropped() {
        let mut filter = RedeliveryFilter::default();
        assert_eq!(admitted(&mut filter, &[(0, 5), (0, 5)]), [true, false]);
    }

    #[test]
    fn every_further_repeat_of_the_last_offset_is_dropped() {
        let mut filter = RedeliveryFilter::default();
        assert_eq!(
            admitted(&mut filter, &[(0, 5), (0, 5), (0, 5)]),
            [true, false, false]
        );
    }

    #[test]
    fn the_offset_after_a_dropped_repeat_is_admitted() {
        let mut filter = RedeliveryFilter::default();
        assert_eq!(
            admitted(&mut filter, &[(0, 5), (0, 5), (0, 6)]),
            [true, false, true]
        );
    }

    #[test]
    fn an_offset_below_the_last_passes_to_the_ledger() {
        let mut filter = RedeliveryFilter::default();
        assert_eq!(
            admitted(&mut filter, &[(0, 5), (0, 6), (0, 5)]),
            [true, true, true]
        );
    }

    #[test]
    fn an_offset_gap_is_admitted() {
        let mut filter = RedeliveryFilter::default();
        assert_eq!(admitted(&mut filter, &[(0, 5), (0, 9)]), [true, true]);
    }

    #[test]
    fn partitions_are_filtered_independently() {
        let mut filter = RedeliveryFilter::default();
        assert_eq!(
            admitted(&mut filter, &[(0, 5), (1, 5), (1, 5), (0, 5)]),
            [true, true, false, false]
        );
    }

    #[test]
    fn the_same_partition_of_another_topic_is_filtered_independently() {
        let mut filter = RedeliveryFilter::default();
        assert!(filter.admit(&tp("events", 0), Offset(5)));
        assert!(filter.admit(&tp("replay", 0), Offset(5)));
        assert!(!filter.admit(&tp("replay", 0), Offset(5)));
    }

    #[test]
    fn a_forgotten_partition_admits_its_last_offset_again() {
        let mut filter = RedeliveryFilter::default();
        admitted(&mut filter, &[(0, 5)]);
        filter.forget(&tp("events", 0));
        assert_eq!(admitted(&mut filter, &[(0, 5)]), [true]);
    }

    #[test]
    fn forgetting_a_partition_keeps_the_others() {
        let mut filter = RedeliveryFilter::default();
        admitted(&mut filter, &[(0, 5), (1, 7)]);
        filter.forget(&tp("events", 0));
        assert_eq!(admitted(&mut filter, &[(0, 5), (1, 7)]), [true, false]);
    }

    #[test]
    fn forgetting_an_unknown_partition_changes_nothing() {
        let mut filter = RedeliveryFilter::default();
        admitted(&mut filter, &[(0, 5)]);
        filter.forget(&tp("events", 3));
        assert_eq!(admitted(&mut filter, &[(0, 5)]), [false]);
    }
}
