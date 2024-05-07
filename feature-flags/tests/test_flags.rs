use anyhow::Result;
use assert_json_diff::assert_json_include;

use reqwest::StatusCode;
use serde_json::{json, Value};

use crate::common::*;
mod common;

#[tokio::test]
async fn it_sends_flag_request() -> Result<()> {
    let token = random_string("token", 16);
    let distinct_id = "user_distinct_id".to_string();

    let config = DEFAULT_CONFIG.clone();

    let server = ServerHandle::for_config(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": distinct_id,
        "groups": {"group1": "group1"}
    });
    let res = server.send_flags_request(payload.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

    // We don't want to deserialize the data into a flagResponse struct here,
    // because we want to assert the shape of the raw json data.
    let json_data = res.json::<Value>().await?;

    assert_json_include!(
        actual: json_data,
        expected: json!({
            "errorWhileComputingFlags": false,
            "featureFlags": {
                "beta-feature": "variant-1",
                "rollout-flag": "true",
            }
        })
    );

    Ok(())
}
