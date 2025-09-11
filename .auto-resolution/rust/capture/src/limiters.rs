use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use common_redis::Client;
use common_types::RawEvent;
use limiters::redis::{QuotaResource, RedisLimiter, ServiceName, QUOTA_LIMITER_CACHE_KEY};
use metrics::counter;

use crate::{
    api::CaptureError,
    config::CaptureMode,
    config::Config,
    prometheus::{report_quota_limit_exceeded, CAPTURE_EVENTS_DROPPED_TOTAL},
    v0_request::ProcessingContext,
};

//
// Add a new predicate function for each new quota limiter you
// add to the CaptureQuotaLimiter. Each should match RawEvents
// associated with the QuotaResource type you will bind to the
// CaptureQuotaLimiter
//

// for QuotaResource::Exceptions
pub fn is_exception_event(event: &RawEvent) -> bool {
    event.event.as_str() == "$exception"
}

// for QuotaResource::Surveys
pub fn is_survey_event(event: &RawEvent) -> bool {
    matches!(
        event.event.as_str(),
        "survey sent" | "survey shown" | "survey dismissed"
    )
}

// for QuotaResource::LLMEvents
pub fn is_llm_event(event: &RawEvent) -> bool {
    event.event.starts_with("$ai_")
}

// TODO: define more limiter predicates here!

/// See server.rs for an example of how to use CaptureQuotaLimiter
/// and to add new scoped limiters to capture
pub struct CaptureQuotaLimiter {
    capture_mode: CaptureMode,

    redis_timeout: Duration,
    redis_key_prefix: Option<String>,
    redis_client: Arc<dyn Client + Send + Sync>,

    // these are scoped to a specific event subset (e.g. survey events, AI events, etc.)
    // and ONLY filter out those events if the quota is exceeded
    scoped_limiters: Vec<Box<dyn ScopedLimiterTrait>>,

    // this is the global billing limiter - if a token matches this limiter bucket,
    // all events are dropped for the incoming payload. Due to this, this limiter
    // IS ALWAYS APPLIED LAST in the chain.
    global_limiter: RedisLimiter,
}

impl CaptureQuotaLimiter {
    pub fn new(
        config: &Config,
        redis_client: Arc<dyn Client + Send + Sync>,
        redis_timeout: Duration,
    ) -> Self {
        let err_msg = format!(
            "failed to create global limiter: {:?}",
            &config.capture_mode
        );
        let global_limiter = RedisLimiter::new(
            redis_timeout,
            redis_client.clone(),
            QUOTA_LIMITER_CACHE_KEY.to_string(),
            config.redis_key_prefix.clone(),
            Self::get_resource_for_mode(config.capture_mode.clone()),
            ServiceName::Capture,
        )
        .expect(&err_msg);

        Self {
            capture_mode: config.capture_mode.clone(),
            redis_timeout,
            redis_key_prefix: config.redis_key_prefix.clone(),
            redis_client: redis_client.clone(),
            global_limiter,
            scoped_limiters: vec![],
        }
    }

    pub fn add_scoped_limiter<F>(mut self, resource: QuotaResource, event_matcher: F) -> Self
    where
        F: Fn(&RawEvent) -> bool + Send + Sync + Clone + 'static,
    {
        let err_msg = format!("failed to create scoped limiter: {resource:?}");
        let limiter = ScopedLimiter::new(
            resource.clone(),
            RedisLimiter::new(
                self.redis_timeout,
                self.redis_client.clone(),
                QUOTA_LIMITER_CACHE_KEY.to_string(),
                self.redis_key_prefix.clone(),
                resource.clone(),
                ServiceName::Capture,
            )
            .expect(&err_msg),
            event_matcher,
        );
        self.scoped_limiters.push(Box::new(limiter));

        self
    }

    pub async fn check_and_filter(
        &self,
        context: &ProcessingContext,
        events: Vec<RawEvent>,
    ) -> Result<Vec<RawEvent>, CaptureError> {
        // in the future, we may bucket quotas by more than token (team)
        // so we accept the whole ProcessingContext here
        let token = context.token.as_str();

        // avoid undue copying and allocations by caching event batch by index
        let mut indices_to_events: HashMap<usize, RawEvent> = HashMap::new();
        let mut filtered_indices: Vec<usize> = vec![];
        let mut retained_indices: Vec<usize> = vec![];
        for (i, event) in events.into_iter().enumerate() {
            indices_to_events.insert(i, event);
            filtered_indices.push(i);
        }

        // for each scoped limiter, if the token is found in Redis,
        // only drop events matching the limiter's filter predicate
        for limiter in self.scoped_limiters.iter() {
            let (matched_indices, unmatched_indices) = limiter
                .partition_event_indices(&indices_to_events, &filtered_indices)
                .await;

            if limiter.is_limited(token).await {
                // retain only events that this limiter doesn't drop
                filtered_indices = unmatched_indices;

                // report quota limit exceeded for this limiter
                let dropped_count = matched_indices.len() as u64;
                if dropped_count > 0 {
                    report_quota_limit_exceeded(limiter.resource(), dropped_count);
                    let dropped_events_tag = format!("{}_over_quota", limiter.resource().as_str());
                    counter!(CAPTURE_EVENTS_DROPPED_TOTAL, "cause" => dropped_events_tag)
                        .increment(dropped_count);
                }
            } else {
                // keep the events this limiter matched around for global limiter
                // to return in the event the global limit is exceeded for this token (team)
                // this way each scoped limiter is independent of the all-or-nothing global limit
                retained_indices.extend(matched_indices.into_iter());
            }

            // if this filtering pass resulted in an empty batch, throw sentinel error
            if filtered_indices.is_empty() {
                // TODO(eli): tag these with QuotaResource type?
                return Err(CaptureError::BillingLimit);
            }
        }

        // drop everything if this limiter is exceeded after all others have filtered the batch
        if self.global_limiter.is_limited(token).await {
            let dropped_count = filtered_indices.len() as u64;
            let global_resource_tag = Self::get_resource_for_mode(self.capture_mode.clone());
            report_quota_limit_exceeded(&global_resource_tag, dropped_count);
            let dropped_events_tag = format!("{}_over_quota", global_resource_tag.as_str());
            counter!(CAPTURE_EVENTS_DROPPED_TOTAL, "cause" => dropped_events_tag)
                .increment(dropped_count);

            // if the global limit was exceeded, we should return only
            // events the scoped limiters didn't already drop, or the
            // sentinel error if there are no retained events
            if retained_indices.is_empty() {
                return Err(CaptureError::BillingLimit);
            } else {
                let retained_events: Vec<RawEvent> = retained_indices
                    .iter()
                    .map(|i| indices_to_events.remove(i).unwrap())
                    .collect();
                return Ok(retained_events);
            }
        }

        // if the scoped limiters didn't empty the batch by this point,
        // and the global billing limit wasn't exceeded, return the
        // remaining events
        let filtered_events: Vec<RawEvent> = filtered_indices
            .iter()
            .map(|i| indices_to_events.remove(i).unwrap())
            .collect();
        Ok(filtered_events)
    }

    pub fn get_resource_for_mode(mode: CaptureMode) -> QuotaResource {
        match mode {
            CaptureMode::Events => QuotaResource::Events,
            CaptureMode::Recordings => QuotaResource::Recordings,
        }
    }
}

#[async_trait::async_trait]
trait ScopedLimiterTrait: Send + Sync {
    async fn is_limited(&self, token: &str) -> bool;
    async fn partition_event_indices(
        &self,
        indices_to_events: &HashMap<usize, RawEvent>,
        indices: &[usize],
    ) -> (Vec<usize>, Vec<usize>);
    fn resource(&self) -> &QuotaResource;
}

#[derive(Clone)]
struct ScopedLimiter<F> {
    resource: QuotaResource,
    limiter: RedisLimiter,
    // predicate supplied here should match RawEvents TO BE DROPPED
    // if the limit for this team/token has been exceeded
    event_matcher: F,
}

impl<F> ScopedLimiter<F>
where
    F: Fn(&RawEvent) -> bool + Send + Sync + Clone,
{
    fn new(resource: QuotaResource, limiter: RedisLimiter, event_matcher: F) -> Self {
        Self {
            resource,
            limiter,
            event_matcher,
        }
    }
}

#[async_trait::async_trait]
impl<F> ScopedLimiterTrait for ScopedLimiter<F>
where
    F: Fn(&RawEvent) -> bool + Send + Sync + Clone,
{
    async fn is_limited(&self, token: &str) -> bool {
        self.limiter.is_limited(token).await
    }

    async fn partition_event_indices(
        &self,
        indices_to_events: &HashMap<usize, RawEvent>,
        indices: &[usize],
    ) -> (Vec<usize>, Vec<usize>) {
        indices.iter().partition(|&i| {
            let e: &RawEvent = indices_to_events.get(i).unwrap();
            (self.event_matcher)(e)
        })
    }

    fn resource(&self) -> &QuotaResource {
        &self.resource
    }
}
