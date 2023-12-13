/// When a customer is writing too often to the same key, we get hot partitions. This negatively
/// affects our write latency and cluster health. We try to provide ordering guarantees wherever
/// possible, but this does require that we map key -> partition.
///
/// If the write-rate reaches a certain amount, we need to be able to handle the hot partition
/// before it causes a negative impact. In this case, instead of passing the error to the customer
/// with a 429, we relax our ordering constraints and temporarily override the key, meaning the
/// customers data will be spread across all partitions.
use std::collections::HashSet;
use std::num::NonZeroU32;
use std::sync::Arc;

use governor::{clock, state::keyed::DefaultKeyedStateStore, Quota, RateLimiter};
use metrics::gauge;
use rand::Rng;

// See: https://docs.rs/governor/latest/governor/_guide/index.html#usage-in-multiple-threads
#[derive(Clone)]
pub struct PartitionLimiter {
    limiter: Arc<RateLimiter<String, DefaultKeyedStateStore<String>, clock::DefaultClock>>,
    forced_keys: HashSet<String>,
}

impl PartitionLimiter {
    pub fn new(per_second: NonZeroU32, burst: NonZeroU32, forced_keys: Option<String>) -> Self {
        let quota = Quota::per_second(per_second).allow_burst(burst);
        let limiter = Arc::new(governor::RateLimiter::dashmap(quota));

        let forced_keys: HashSet<String> = match forced_keys {
            None => HashSet::new(),
            Some(values) => values.split(',').map(String::from).collect(),
        };

        PartitionLimiter {
            limiter,
            forced_keys,
        }
    }

    pub fn is_limited(&self, key: &String) -> bool {
        self.forced_keys.contains(key) || self.limiter.check_key(key).is_err()
    }

    /// Reports the number of tracked keys to prometheus every 10 seconds,
    /// needs to be spawned in a separate task.
    pub async fn report_metrics(&self) {
        let mut interval = tokio::time::interval(tokio::time::Duration::from_secs(10));
        loop {
            interval.tick().await;
            gauge!("partition_limits_key_count", self.limiter.len() as f64);
        }
    }

    /// Clean up the rate limiter state, once per minute. Ensure we don't use more memory than
    /// necessary.
    pub async fn clean_state(&self) {
        // Give a small amount of randomness to the interval to ensure we don't have all replicas
        // locking at the same time. The lock isn't going to be held for long, but this will reduce
        // impact regardless.
        let interval_secs = rand::thread_rng().gen_range(60..70);

        let mut interval = tokio::time::interval(tokio::time::Duration::from_secs(interval_secs));
        loop {
            interval.tick().await;

            self.limiter.retain_recent();
            self.limiter.shrink_to_fit();
        }
    }
}

#[cfg(test)]
mod tests {
    use crate::partition_limits::PartitionLimiter;
    use std::num::NonZeroU32;

    #[tokio::test]
    async fn low_limits() {
        let limiter = PartitionLimiter::new(
            NonZeroU32::new(1).unwrap(),
            NonZeroU32::new(1).unwrap(),
            None,
        );
        let token = String::from("test");

        assert!(!limiter.is_limited(&token));
        assert!(limiter.is_limited(&token));
    }

    #[tokio::test]
    async fn bursting() {
        let limiter = PartitionLimiter::new(
            NonZeroU32::new(1).unwrap(),
            NonZeroU32::new(3).unwrap(),
            None,
        );
        let token = String::from("test");

        assert!(!limiter.is_limited(&token));
        assert!(!limiter.is_limited(&token));
        assert!(!limiter.is_limited(&token));
        assert!(limiter.is_limited(&token));
    }

    #[tokio::test]
    async fn forced_key() {
        let key_one = String::from("one");
        let key_two = String::from("two");
        let key_three = String::from("three");
        let forced_keys = Some(String::from("one,three"));

        let limiter = PartitionLimiter::new(
            NonZeroU32::new(1).unwrap(),
            NonZeroU32::new(1).unwrap(),
            forced_keys,
        );

        // One and three are limited from the start, two is not
        assert!(limiter.is_limited(&key_one));
        assert!(!limiter.is_limited(&key_two));
        assert!(limiter.is_limited(&key_three));

        // Two is limited on the second event
        assert!(limiter.is_limited(&key_two));
    }
}
