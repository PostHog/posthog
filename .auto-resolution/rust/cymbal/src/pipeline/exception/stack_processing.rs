use std::{collections::HashMap, sync::Arc};

use uuid::Uuid;

use crate::{
    app_context::AppContext,
    error::{PipelineResult, UnhandledError},
    fingerprinting::resolve_fingerprint,
    metric_consts::{FINGERPRINT_BATCH_TIME, FRAME_BATCH_TIME, FRAME_RESOLUTION},
    types::{FingerprintedErrProps, RawErrProps, Stacktrace},
};

pub async fn do_stack_processing(
    context: Arc<AppContext>,
    events: &[PipelineResult],
    mut indexed_props: Vec<(usize, RawErrProps)>,
) -> Result<Vec<(usize, FingerprintedErrProps)>, (usize, UnhandledError)> {
    let frame_batch_timer = common_metrics::timing_guard(FRAME_BATCH_TIME, &[]);
    let mut frame_resolve_handles = HashMap::new();
    for (index, props) in indexed_props.iter_mut() {
        let team_id = events[*index]
            .as_ref()
            .expect("no events have been dropped since indexed-property gathering")
            .team_id;

        for exception in props.exception_list.iter_mut() {
            exception.exception_id = Some(Uuid::now_v7().to_string());
            let frames = match exception.stack.take() {
                Some(Stacktrace::Raw { frames }) => {
                    if frames.is_empty() {
                        continue;
                    }
                    frames
                }
                Some(Stacktrace::Resolved { frames }) => {
                    // This stack trace is already resolved, we have no work to do.
                    exception.stack = Some(Stacktrace::Resolved { frames });
                    continue;
                }
                None => {
                    continue; // It was None before and it's none after the take
                }
            };

            for frame in frames.iter() {
                let id = frame.frame_id();
                if frame_resolve_handles.contains_key(&id) {
                    // We've already spawned a task to resolve this frame, so we don't need to do it again.
                    continue;
                }

                // We need a cloned frame to move into the closure below
                let frame = frame.clone();
                let context = context.clone();
                // Spawn a concurrent task for resolving every frame
                let handle = tokio::spawn(async move {
                    context.worker_liveness.report_healthy().await;
                    metrics::counter!(FRAME_RESOLUTION).increment(1);
                    let res = context
                        .resolver
                        .resolve(&frame, team_id, &context.pool, &context.catalog)
                        .await;
                    context.worker_liveness.report_healthy().await;
                    res
                });
                frame_resolve_handles.insert(id, handle);
            }

            // Put the frames back on the exception, now that we're done mutating them until we've
            // gathered our lookup table.
            exception.stack = Some(Stacktrace::Raw { frames });
        }
    }

    let mut frame_lookup_table = HashMap::new();
    for (id, handle) in frame_resolve_handles.into_iter() {
        let res = match handle.await.expect("Frame resolve task didn't panic") {
            Ok(r) => r,
            Err(e) => {
                let index = find_index_with_matching_frame_id(&id, &indexed_props);
                return Err((index, e));
            }
        };
        frame_lookup_table.insert(id, res);
    }
    frame_batch_timer.fin();

    let fingerprint_timer = common_metrics::timing_guard(FINGERPRINT_BATCH_TIME, &[]);
    let mut indexed_fingerprinted = Vec::new();
    for (index, mut props) in indexed_props.into_iter() {
        for exception in props.exception_list.iter_mut() {
            exception.stack = exception
                .stack
                .take()
                .map(|s| {
                    s.resolve(&frame_lookup_table).ok_or(UnhandledError::Other(
                        "Stacktrace::resolve returned None".to_string(),
                    ))
                })
                .transpose()
                .map_err(|e| (index, e))?
        }

        let team_id = events[index]
            .as_ref()
            .expect("no events have been dropped since indexed-property gathering")
            .team_id;

        let mut conn = context
            .pool
            .acquire()
            .await
            .map_err(|e| (index, e.into()))?;

        let proposed = resolve_fingerprint(&mut conn, &context.team_manager, team_id, &props)
            .await
            .map_err(|e| (index, e))?;

        let fingerprinted = props.to_fingerprinted(proposed);
        indexed_fingerprinted.push((index, fingerprinted));
    }
    fingerprint_timer.fin(); // Could just let this be dropped, tbh

    Ok(indexed_fingerprinted)
}

fn find_index_with_matching_frame_id(id: &str, list: &[(usize, RawErrProps)]) -> usize {
    for (index, props) in list.iter() {
        for exception in props.exception_list.iter() {
            if let Some(Stacktrace::Raw { frames }) = &exception.stack {
                for frame in frames {
                    if frame.frame_id() == id {
                        return *index;
                    }
                }
            }
        }
    }
    0
}
