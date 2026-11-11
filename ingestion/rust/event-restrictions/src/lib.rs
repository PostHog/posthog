//! Per-token event restrictions (drop, overflow, redirect) that capture and the replay
//! recorder apply, loaded from Redis one pipeline slice at a time.

mod manager;
mod repository;
mod types;

// Re-export public API
pub use manager::{EventRestrictionService, RestrictionManager};
pub use repository::{EventRestrictionsRepository, RedisRestrictionsRepository, RestrictionEntry};
pub use types::{
    AppliedRestrictions, EventContext, Pipeline, Restriction, RestrictionFilters, RestrictionScope,
    RestrictionType,
};

#[cfg(any(test, feature = "test-utils"))]
pub use repository::testing::MockRestrictionsRepository;
