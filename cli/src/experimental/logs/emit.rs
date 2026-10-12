use std::collections::BTreeMap;

use serde_json::{json, Value as Json};

use super::mapping::MappedRecord;

/// A batch of records serialized as one OTLP/JSON request body.
///
/// The intake accepts protobuf or JSON, and JSON keeps `opentelemetry-proto` out of a binary that
/// ships to seven targets through npm.
#[derive(Debug, Clone, PartialEq)]
pub struct Batch {
    pub body: Vec<u8>,
    pub records: usize,
}

/// Groups records into request bodies that each stay under `max_bytes`.
///
/// Sizes each record once and accumulates, rather than re-encoding the batch per record, which
/// would be quadratic in the batch size. The running total counts every record's resource
/// attributes, while the encoded body writes them once per distinct resource, so the estimate is
/// never below the real body and a batch cannot overshoot the ceiling.
///
/// A single record over the ceiling still becomes its own batch. Dropping it would lose data
/// silently, and the intake answers an oversized body with 413, which the caller surfaces.
pub fn batch_records(records: &[MappedRecord], max_bytes: usize) -> Vec<Batch> {
    // `{"resourceLogs":[{"resource":{"attributes":[]},"scopeLogs":[{"logRecords":[]}]}]}`
    const ENVELOPE_BYTES: usize = 128;

    let mut batches = Vec::new();
    let mut current: Vec<&MappedRecord> = Vec::new();
    let mut estimate = ENVELOPE_BYTES;

    for record in records {
        let size = estimated_size(record);

        if !current.is_empty() && estimate + size > max_bytes {
            batches.push(Batch {
                body: encode(&current),
                records: current.len(),
            });
            current.clear();
            estimate = ENVELOPE_BYTES;
        }

        current.push(record);
        estimate += size;
    }

    if !current.is_empty() {
        batches.push(Batch {
            body: encode(&current),
            records: current.len(),
        });
    }

    batches
}

/// Upper bound on the bytes one record adds, counting its resource attributes even though the
/// encoder writes them once per resource group.
fn estimated_size(record: &MappedRecord) -> usize {
    let log = serde_json::to_vec(&log_record(record)).map_or(0, |bytes| bytes.len());
    let resource: usize = record
        .resource_attributes
        .iter()
        .map(|(key, value)| key.len() + value.len() + 40)
        .sum();
    let service = record
        .service_name
        .as_ref()
        .map_or(0, |name| name.len() + 52);
    // One comma between array elements, plus the per-resource scopeLogs wrapper.
    log + resource + service + 96
}

/// One OTLP/JSON `resourceLogs` entry per distinct resource, which is what keeps the resource
/// attributes from repeating on every record.
fn encode(records: &[&MappedRecord]) -> Vec<u8> {
    let mut grouped: BTreeMap<Vec<(String, String)>, Vec<&MappedRecord>> = BTreeMap::new();
    for record in records {
        grouped
            .entry(resource_key(record))
            .or_default()
            .push(record);
    }

    let resource_logs: Vec<Json> = grouped
        .into_iter()
        .map(|(key, records)| {
            json!({
                "resource": { "attributes": attributes(key.into_iter()) },
                "scopeLogs": [{ "logRecords": records.iter().map(|r| log_record(r)).collect::<Vec<_>>() }],
            })
        })
        .collect();

    serde_json::to_vec(&json!({ "resourceLogs": resource_logs })).unwrap_or_default()
}

/// `service.name` joins the resource attributes, so records that share a service and labels share
/// one resource block.
fn resource_key(record: &MappedRecord) -> Vec<(String, String)> {
    let mut key: Vec<(String, String)> = record
        .resource_attributes
        .iter()
        .map(|(k, v)| (k.clone(), v.clone()))
        .collect();
    if let Some(service) = &record.service_name {
        key.push(("service.name".to_string(), service.clone()));
    }
    key.sort();
    key
}

fn attributes(pairs: impl Iterator<Item = (String, String)>) -> Vec<Json> {
    pairs
        .map(|(key, value)| json!({ "key": key, "value": { "stringValue": value } }))
        .collect()
}

fn log_record(record: &MappedRecord) -> Json {
    let mut fields = json!({
        "timeUnixNano": record.timestamp_ns.to_string(),
        "body": { "stringValue": record.body },
        "attributes": attributes(record.attributes.iter().map(|(k, v)| (k.clone(), v.clone()))),
    });

    let object = fields.as_object_mut().expect("built from a json! object");
    if let Some((text, number)) = &record.severity {
        object.insert("severityText".to_string(), json!(text));
        object.insert("severityNumber".to_string(), json!(number));
    }
    // OTLP/JSON carries trace and span ids as hex strings. Lowercase them so they join the
    // spans table, which stores them uppercase but matches on a normalized form.
    if let Some(trace_id) = &record.trace_id {
        object.insert("traceId".to_string(), json!(trace_id.to_lowercase()));
    }
    if let Some(span_id) = &record.span_id {
        object.insert("spanId".to_string(), json!(span_id.to_lowercase()));
    }

    fields
}

#[cfg(test)]
mod tests {
    use super::*;

    fn record(service: &str, body: &str) -> MappedRecord {
        MappedRecord {
            timestamp_ns: 1_700_000_000_000_000_000,
            body: body.to_string(),
            service_name: Some(service.to_string()),
            severity: Some(("error".to_string(), 17)),
            trace_id: None,
            span_id: None,
            resource_attributes: BTreeMap::from([("namespace".to_string(), "prod".to_string())]),
            attributes: BTreeMap::from([("pod".to_string(), "abc".to_string())]),
        }
    }

    #[test]
    fn every_batch_stays_under_the_ceiling() {
        let records: Vec<MappedRecord> = (0..500)
            .map(|i| {
                record(
                    "api",
                    &format!("line {i} with some padding to give it weight"),
                )
            })
            .collect();

        let batches = batch_records(&records, 4096);

        assert!(batches.len() > 1, "expected the ceiling to force a split");
        for batch in &batches {
            assert!(
                batch.body.len() <= 4096,
                "a batch encoded to {} bytes, over the 4096 ceiling",
                batch.body.len()
            );
        }
        let total: usize = batches.iter().map(|b| b.records).sum();
        assert_eq!(total, 500, "every record must land in exactly one batch");
    }

    #[test]
    fn batching_is_linear_enough_to_handle_a_real_shard() {
        // The first implementation re-encoded the whole batch per record, which made this hang.
        let records: Vec<MappedRecord> = (0..20_000)
            .map(|i| record("api", &format!("line {i}")))
            .collect();

        let batches = batch_records(&records, 1_500_000);

        let total: usize = batches.iter().map(|b| b.records).sum();
        assert_eq!(total, 20_000);
    }

    #[test]
    fn a_record_over_the_ceiling_becomes_its_own_batch_rather_than_being_dropped() {
        let records = vec![
            record("api", "small"),
            record("api", &"x".repeat(9000)),
            record("api", "small again"),
        ];

        let batches = batch_records(&records, 4096);

        let total: usize = batches.iter().map(|b| b.records).sum();
        assert_eq!(total, 3, "the oversized record must still be emitted");
    }

    #[test]
    fn records_sharing_a_resource_are_written_under_one_resource_block() {
        let batches = batch_records(
            &[
                record("api", "one"),
                record("api", "two"),
                record("web", "three"),
            ],
            1_000_000,
        );

        let json: serde_json::Value = serde_json::from_slice(&batches[0].body).expect("valid json");
        let resources = json["resourceLogs"].as_array().expect("resourceLogs");

        assert_eq!(resources.len(), 2, "one block per distinct service");
    }

    #[test]
    fn severity_and_ids_are_omitted_rather_than_sent_empty() {
        let mut bare = record("api", "line");
        bare.severity = None;
        bare.service_name = None;

        let batches = batch_records(&[bare], 1_000_000);
        let json: serde_json::Value = serde_json::from_slice(&batches[0].body).expect("valid json");
        let log = &json["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0];

        assert!(log.get("severityText").is_none());
        assert!(log.get("traceId").is_none());
        assert_eq!(log["body"]["stringValue"], "line");
    }
}
