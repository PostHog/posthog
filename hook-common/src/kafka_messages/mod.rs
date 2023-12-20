pub mod app_metrics;
pub mod plugin_logs;

use chrono::{DateTime, NaiveDateTime, Utc};
use serde::{Deserialize, Deserializer, Serializer};

pub fn serialize_datetime<S>(datetime: &DateTime<Utc>, serializer: S) -> Result<S::Ok, S::Error>
where
    S: Serializer,
{
    serializer.serialize_str(&datetime.format("%Y-%m-%d %H:%M:%S").to_string())
}

pub fn deserialize_datetime<'de, D>(deserializer: D) -> Result<DateTime<Utc>, D::Error>
where
    D: Deserializer<'de>,
{
    let formatted: String = Deserialize::deserialize(deserializer)?;
    let datetime = match NaiveDateTime::parse_from_str(&formatted, "%Y-%m-%d %H:%M:%S") {
        Ok(d) => d.and_utc(),
        Err(_) => return Err(serde::de::Error::custom("Invalid datetime format")),
    };

    Ok(datetime)
}
