use metrics::counter;
use tracing::info;

use crate::{app_context::AppContext, error::PipelineFailure, metric_consts::DROPPED_EVENTS};

use super::IncomingEvent;

pub async fn apply_billing_limits(
    in_buf: Vec<IncomingEvent>,
    context: &AppContext,
) -> Result<Vec<IncomingEvent>, PipelineFailure> {
    let start_count = in_buf.len();

    let mut out = Vec::with_capacity(in_buf.len());

    for event in in_buf {
        let IncomingEvent::Captured(e) = event else {
            // If this event has already been processed, quota limiting has
            // already been applied.
            out.push(event);
            continue;
        };

        if context.billing_limiter.is_limited(&e.token).await {
            info!("Dropped event for {}", &e.token);
            continue;
        }
        out.push(IncomingEvent::Captured(e));
    }

    counter!(DROPPED_EVENTS, "reason" => "billing_limit")
        .increment((start_count - out.len()) as u64);

    Ok(out)
}
