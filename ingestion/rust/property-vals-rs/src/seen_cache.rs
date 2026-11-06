use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use quick_cache::{sync, DefaultHashBuilder, Lifecycle, UnitWeighter};

use crate::metrics_consts::{
    SEEN_CACHE_EVICTED, SEEN_CACHE_HITS, SEEN_CACHE_MISSES, SEEN_CACHE_ROLLS,
};
use crate::types::TupleKey;

#[derive(Clone)]
struct EvictingLifecycle {
    worker: &'static str,
}

impl Lifecycle<TupleKey, ()> for EvictingLifecycle {
    type RequestState = ();

    fn begin_request(&self) -> Self::RequestState {}

    fn on_evict(&self, _state: &mut Self::RequestState, _key: TupleKey, _val: ()) {
        metrics::counter!(SEEN_CACHE_EVICTED, "worker" => self.worker).increment(1);
    }
}

type Inner = sync::Cache<TupleKey, (), UnitWeighter, DefaultHashBuilder, EvictingLifecycle>;

pub struct SeenCache {
    cache: Inner,
    worker: &'static str,
    day: AtomicU64,
}

pub fn utc_day() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|since_epoch| since_epoch.as_secs() / 86_400)
        .unwrap_or(0)
}

impl SeenCache {
    pub fn new(capacity: usize, worker: &'static str) -> Self {
        let cache = sync::Cache::with(
            capacity,
            capacity as u64,
            UnitWeighter,
            DefaultHashBuilder::default(),
            EvictingLifecycle { worker },
        );
        Self {
            cache,
            worker,
            day: AtomicU64::new(utc_day()),
        }
    }

    pub fn roll(&self, day: u64) {
        if self.day.swap(day, Ordering::AcqRel) == day {
            return;
        }
        self.cache.clear();
        metrics::counter!(SEEN_CACHE_ROLLS, "worker" => self.worker).increment(1);
    }

    pub fn seen(&self, key: &TupleKey) -> bool {
        if self.cache.get(key).is_some() {
            metrics::counter!(SEEN_CACHE_HITS, "worker" => self.worker).increment(1);
            true
        } else {
            metrics::counter!(SEEN_CACHE_MISSES, "worker" => self.worker).increment(1);
            false
        }
    }

    pub fn insert(&self, key: &TupleKey) {
        self.cache.insert(key.clone(), ());
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::PropertyType;

    fn tuple(value: &str) -> TupleKey {
        TupleKey {
            team_id: 2,
            property_type: PropertyType::Event,
            property_key: "$browser".to_string(),
            property_value: value.to_string(),
        }
    }

    #[test]
    fn roll_clears_entries_only_when_the_day_changes() {
        let cache = SeenCache::new(1000, "test");
        cache.roll(100);
        cache.insert(&tuple("Chrome"));

        cache.roll(100);
        assert!(cache.seen(&tuple("Chrome")), "same day keeps entries");

        cache.roll(101);
        assert!(!cache.seen(&tuple("Chrome")), "new day clears entries");
    }
}
