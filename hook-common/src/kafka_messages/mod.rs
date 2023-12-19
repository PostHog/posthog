pub mod app_metrics;
pub mod plugin_logs;

use chrono::{DateTime, Utc};
use serde::Serializer;
use uuid::Uuid;

pub fn serialize_uuid<S>(uuid: &Uuid, serializer: S) -> Result<S::Ok, S::Error>
where
    S: Serializer,
{
    serializer.serialize_str(&uuid.to_string())
}

pub fn serialize_optional_uuid<S>(uuid: &Option<Uuid>, serializer: S) -> Result<S::Ok, S::Error>
where
    S: Serializer,
{
    match uuid {
        Some(uuid) => serializer.serialize_str(&uuid.to_string()),
        None => serializer.serialize_none(),
    }
}

pub fn serialize_datetime<S>(datetime: &DateTime<Utc>, serializer: S) -> Result<S::Ok, S::Error>
where
    S: Serializer,
{
    serializer.serialize_str(&datetime.format("%Y-%m-%d %H:%M:%S%.f").to_string())
}
