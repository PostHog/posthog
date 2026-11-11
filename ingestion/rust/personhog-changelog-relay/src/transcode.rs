//! A changelog record as the `clickhouse_person` row Node's
//! `generateKafkaPersonUpdateMessage` produces.

use chrono::DateTime;
use personhog_proto::personhog::types::v1::Person;
use prost::Message;
use serde::Serialize;

/// Why a record cannot become a row. These records go to the DLQ, since
/// retrying them can never succeed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Poison {
    Empty,
    Decode(String),
    Uuid(String),
    Properties,
    Timestamp(i64),
}

impl Poison {
    pub fn reason(&self) -> &'static str {
        match self {
            Poison::Empty => "empty",
            Poison::Decode(_) => "decode",
            Poison::Uuid(_) => "uuid",
            Poison::Properties => "properties",
            Poison::Timestamp(_) => "timestamp",
        }
    }
}

impl std::fmt::Display for Poison {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Poison::Empty => write!(f, "record has no payload"),
            Poison::Decode(e) => write!(f, "not a Person proto: {e}"),
            Poison::Uuid(uuid) => write!(f, "uuid {uuid:?} does not parse"),
            Poison::Properties => write!(f, "properties are not UTF-8"),
            Poison::Timestamp(ms) => write!(f, "timestamp {ms} ms is out of range"),
        }
    }
}

#[derive(Serialize)]
struct PersonRow<'a> {
    id: &'a str,
    created_at: String,
    properties: &'a str,
    team_id: i64,
    is_identified: u8,
    is_deleted: u8,
    version: i64,
    last_seen_at: Option<String>,
}

/// ClickHouse second precision in UTC, as Node writes it.
fn clickhouse_seconds(ms: i64) -> Result<String, Poison> {
    DateTime::from_timestamp_millis(ms)
        .map(|t| t.format("%Y-%m-%d %H:%M:%S").to_string())
        .ok_or(Poison::Timestamp(ms))
}

pub fn person_row(payload: Option<&[u8]>) -> Result<Vec<u8>, Poison> {
    let payload = payload.ok_or(Poison::Empty)?;
    let person = Person::decode(payload).map_err(|e| Poison::Decode(e.to_string()))?;
    // ClickHouse stops its whole Kafka consumer on a row whose id is not a UUID.
    uuid::Uuid::parse_str(&person.uuid).map_err(|_| Poison::Uuid(person.uuid.clone()))?;
    let properties = match person.properties.as_slice() {
        [] => "{}",
        bytes => std::str::from_utf8(bytes).map_err(|_| Poison::Properties)?,
    };
    let row = PersonRow {
        id: &person.uuid,
        created_at: clickhouse_seconds(person.created_at)?,
        properties,
        team_id: person.team_id,
        is_identified: u8::from(person.is_identified),
        is_deleted: u8::from(person.is_deleted),
        version: person.version,
        last_seen_at: person.last_seen_at.map(clickhouse_seconds).transpose()?,
    };
    Ok(serde_json::to_vec(&row).expect("a row of strings and integers serializes"))
}

#[cfg(test)]
mod tests {
    use super::*;

    const UUID: &str = "0192f3a1-7c4e-7a3b-9d2e-5f6a7b8c9d0e";

    fn person() -> Person {
        Person {
            id: 42,
            uuid: UUID.to_string(),
            team_id: 7,
            properties: br#"{"email":"a@example.com"}"#.to_vec(),
            created_at: 1_700_000_000_123,
            version: 3,
            is_identified: true,
            last_seen_at: Some(1_700_000_100_999),
            ..Default::default()
        }
    }

    fn row(person: &Person) -> Result<String, Poison> {
        person_row(Some(&person.encode_to_vec())).map(|b| String::from_utf8(b).unwrap())
    }

    #[test]
    fn a_person_becomes_nodes_row() {
        assert_eq!(
            row(&person()).unwrap(),
            r#"{"id":"0192f3a1-7c4e-7a3b-9d2e-5f6a7b8c9d0e","created_at":"2023-11-14 22:13:20","properties":"{\"email\":\"a@example.com\"}","team_id":7,"is_identified":1,"is_deleted":0,"version":3,"last_seen_at":"2023-11-14 22:15:00"}"#
        );
    }

    #[test]
    fn a_death_document_is_a_deleted_row_with_empty_properties() {
        let dead = Person {
            properties: Vec::new(),
            is_deleted: true,
            is_identified: false,
            last_seen_at: None,
            version: 4,
            ..person()
        };
        assert_eq!(
            row(&dead).unwrap(),
            r#"{"id":"0192f3a1-7c4e-7a3b-9d2e-5f6a7b8c9d0e","created_at":"2023-11-14 22:13:20","properties":"{}","team_id":7,"is_identified":0,"is_deleted":1,"version":4,"last_seen_at":null}"#
        );
    }

    #[test]
    fn unrelayable_records_are_poison() {
        let cases: [(&str, Result<String, Poison>, &str); 4] = [
            (
                "no payload",
                person_row(None).map(|_| String::new()),
                "empty",
            ),
            (
                "not a proto",
                person_row(Some(&[0xFF; 8])).map(|_| String::new()),
                "decode",
            ),
            (
                "bad uuid",
                row(&Person {
                    uuid: "nope".to_string(),
                    ..person()
                }),
                "uuid",
            ),
            (
                "bad properties",
                row(&Person {
                    properties: vec![0xC3, 0x28],
                    ..person()
                }),
                "properties",
            ),
        ];
        for (name, result, reason) in cases {
            assert_eq!(result.unwrap_err().reason(), reason, "{name}");
        }
    }
}
