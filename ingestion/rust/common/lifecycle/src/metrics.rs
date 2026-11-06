pub(crate) const METRIC_SHUTDOWN_INITIATED: &str = "lifecycle_shutdown_initiated_total";
pub(crate) const METRIC_SHUTDOWN_COMPLETED: &str = "lifecycle_shutdown_completed_total";
pub(crate) const METRIC_COMPONENT_SHUTDOWN_DURATION: &str =
    "lifecycle_component_shutdown_duration_seconds";
pub(crate) const METRIC_COMPONENT_SHUTDOWN_RESULT: &str =
    "lifecycle_component_shutdown_result_total";

pub(crate) fn emit_shutdown_initiated(
    service_name: &str,
    trigger_component: &str,
    trigger_reason: &str,
) {
    metrics::counter!(
        METRIC_SHUTDOWN_INITIATED,
        "service_name" => service_name.to_string(),
        "trigger_component" => trigger_component.to_string(),
        "trigger_reason" => trigger_reason.to_string()
    )
    .increment(1);
}

pub(crate) fn emit_shutdown_completed(service_name: &str, clean: bool) {
    metrics::counter!(
        METRIC_SHUTDOWN_COMPLETED,
        "service_name" => service_name.to_string(),
        "clean" => clean.to_string()
    )
    .increment(1);
}

pub(crate) fn emit_component_shutdown_duration(
    service_name: &str,
    component: &str,
    result: &str,
    duration_secs: f64,
) {
    metrics::histogram!(
        METRIC_COMPONENT_SHUTDOWN_DURATION,
        "service_name" => service_name.to_string(),
        "component" => component.to_string(),
        "result" => result.to_string()
    )
    .record(duration_secs);
}

pub(crate) fn emit_component_shutdown_result(service_name: &str, component: &str, result: &str) {
    metrics::counter!(
        METRIC_COMPONENT_SHUTDOWN_RESULT,
        "service_name" => service_name.to_string(),
        "component" => component.to_string(),
        "result" => result.to_string()
    )
    .increment(1);
}
