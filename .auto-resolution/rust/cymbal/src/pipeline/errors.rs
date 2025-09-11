use std::sync::Arc;

use common_types::ClickHouseEvent;
use metrics::counter;
use tracing::{error, warn};

use crate::{
    app_context::AppContext,
    error::{EventError, PipelineResult},
    metric_consts::DROPPED_EVENTS,
};

// This exclusively handles errors that have caused events to be dropped. Throughout the cymbal pipeline,
// if an error is encountered that should be displayed to the user, rather than causing an event to be dropped,
// we put it the error message into the events properties. Errors that cause the event to be unhandleable are
// caught here, after the event pipeline, and we emit metrics and, potentially, warning events, in response to them.
pub async fn handle_errors(
    buffer: Vec<PipelineResult>,
    context: Arc<AppContext>,
) -> Vec<ClickHouseEvent> {
    let mut out = Vec::with_capacity(buffer.len());

    for result in buffer {
        match result {
            Ok(event) => out.push(event),
            Err(err) => report_error(context.clone(), err).await,
        }
    }

    out
}

pub async fn report_error(_context: Arc<AppContext>, error: EventError) {
    match error {
        EventError::WrongEventType(_, _) => {
            // TODO - right now, we just pass these through, skipping exception processing but doing
            // all other processing for them. Since encountering this implies a pipeline setup error,
            // we should probably actually panic, or similar, on encountering non-exception events
            error!("{}", error);
            counter!(DROPPED_EVENTS, "reason" => "wrong_event_type").increment(1);
        }
        EventError::NoProperties(_) => {
            // Emitted during exception processing stage, and generally put onto the
            // event rather than causing the event to be dropped
            warn!("{}", error);
            counter!(DROPPED_EVENTS, "reason" => "no_properties").increment(1);
        }
        EventError::InvalidProperties(_, _) => {
            // As above, these generally get put onto events, rather than replacing them in the pipeline
            warn!("{}", error);
            counter!(DROPPED_EVENTS, "reason" => "invalid_properties").increment(1);
        }
        EventError::EmptyExceptionList(_) => {
            // As above, these generally get put onto events, rather than replacing them in the pipeline
            warn!("{}", error);
            counter!(DROPPED_EVENTS, "reason" => "empty_exception_list").increment(1);
        }
        EventError::InvalidTimestamp(_, _) => {
            // We drop events with invalid timestamps, rather than passing them through with some default
            // value, because as a new product we can make stronger guarantees about the validity of timestamps.
            // TODO - we should emit an ingestion warning for these
            warn!("{}", error);
            counter!(DROPPED_EVENTS, "reason" => "invalid_timestamp").increment(1);
        }
        EventError::NoTeamForToken(_) => {
            // This is mundane, and we should simply drop the event - no need for a warning or anything
            counter!(DROPPED_EVENTS, "reason" => "no_team_for_token").increment(1);
        }
        EventError::Suppressed(_) => {
            // This is mundane, and the feature working as expected. We could maybe track the number of suppressed events
            // for a given team somehow, in a "look how much money we're saving you" way, but for now, just dropping them is
            // fine.
            counter!(DROPPED_EVENTS, "reason" => "suppressed").increment(1);
        }
        EventError::FailedToDeserialize(_, _) => {
            // TODO - we should emit these events to a dead letter queue, and potentially panic here,
            // as receiving events we can't process from capture indicates a potential capture issue.
            error!("{}", error);
            counter!(DROPPED_EVENTS, "reason" => "failed_to_deserialize").increment(1);
        }
        EventError::FilteredByTeamId => {
            // Totally mundane
            counter!(DROPPED_EVENTS, "reason" => "filtered_by_team_id").increment(1);
        }
    }
}
