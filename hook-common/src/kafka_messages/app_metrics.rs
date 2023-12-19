use chrono::{DateTime, Utc};
use serde::{Serialize, Serializer};
use uuid::Uuid;

use super::{serialize_datetime, serialize_uuid};

#[derive(Serialize)]
pub enum AppMetricCategory {
    ProcessEvent,
    OnEvent,
    ScheduledTask,
    Webhook,
    ComposeWebhook,
}

#[derive(Serialize, Debug)]
pub enum ErrorType {
    Timeout,
    Connection,
    HttpStatus(u16),
    Parse,
}

#[derive(Serialize, Debug)]
pub struct ErrorDetails {
    pub error: Error,
    // TODO: The plugin-server sends the entire raw event with errors. In order to do this, we'll
    // have to pass the entire event when we enqueue items, and store it in the Parameters JSONB
    // column. We should see if it's possible to work around this before we commit to it.
    //
    // event: Value,
}

#[derive(Serialize, Debug)]
pub struct Error {
    pub name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
    // TODO: Realistically, it doesn't seem likely that we'll generate Rust stack traces and put
    // them here. I think this was more useful in plugin-server when the stack could come from
    // plugin code.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub stack: Option<String>,
}

#[derive(Serialize)]
pub struct AppMetric {
    #[serde(serialize_with = "serialize_datetime")]
    pub timestamp: DateTime<Utc>,
    pub team_id: u32,
    pub plugin_config_id: u32,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub job_id: Option<String>,
    #[serde(serialize_with = "serialize_category")]
    pub category: AppMetricCategory,
    pub successes: u32,
    pub successes_on_retry: u32,
    pub failures: u32,
    #[serde(serialize_with = "serialize_uuid")]
    pub error_uuid: Uuid,
    #[serde(serialize_with = "serialize_error_type")]
    pub error_type: ErrorType,
    pub error_details: Error,
}

fn serialize_category<S>(category: &AppMetricCategory, serializer: S) -> Result<S::Ok, S::Error>
where
    S: Serializer,
{
    let category_str = match category {
        AppMetricCategory::ProcessEvent => "processEvent",
        AppMetricCategory::OnEvent => "onEvent",
        AppMetricCategory::ScheduledTask => "scheduledTask",
        AppMetricCategory::Webhook => "webhook",
        AppMetricCategory::ComposeWebhook => "composeWebhook",
    };
    serializer.serialize_str(category_str)
}

fn serialize_error_type<S>(error_type: &ErrorType, serializer: S) -> Result<S::Ok, S::Error>
where
    S: Serializer,
{
    let error_type = match error_type {
        ErrorType::Connection => "Connection Error".to_owned(),
        ErrorType::Timeout => "Timeout".to_owned(),
        ErrorType::HttpStatus(s) => format!("HTTP Status: {}", s),
        ErrorType::Parse => "Parse Error".to_owned(),
    };
    serializer.serialize_str(&error_type)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_app_metric_serialization() {
        use chrono::prelude::*;

        let app_metric = AppMetric {
            timestamp: Utc.with_ymd_and_hms(2023, 12, 14, 12, 2, 0).unwrap(),
            team_id: 123,
            plugin_config_id: 456,
            job_id: None,
            category: AppMetricCategory::Webhook,
            successes: 10,
            successes_on_retry: 0,
            failures: 2,
            error_uuid: Uuid::parse_str("550e8400-e29b-41d4-a716-446655447777").unwrap(),
            error_type: ErrorType::Connection,
            error_details: Error {
                name: "FooError".to_owned(),
                message: Some("Error Message".to_owned()),
                stack: None,
            },
        };

        let serialized_json = serde_json::to_string(&app_metric).unwrap();

        let expected_json = r#"{"timestamp":"2023-12-14 12:02:00","team_id":123,"plugin_config_id":456,"category":"webhook","successes":10,"successes_on_retry":0,"failures":2,"error_uuid":"550e8400-e29b-41d4-a716-446655447777","error_type":"Connection Error","error_details":{"name":"FooError","message":"Error Message"}}"#;

        assert_eq!(serialized_json, expected_json);
    }
}
