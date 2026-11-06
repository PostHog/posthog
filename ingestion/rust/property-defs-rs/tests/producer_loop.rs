use std::sync::Arc;
use std::time::Duration;

use rdkafka::producer::FutureRecord;
use serde_json::json;

use common_kafka::kafka_consumer::SingleTopicConsumer;
use property_defs_rs::{
    config::Config, measuring_channel::measuring_channel, types::Update, update_cache::Cache,
    update_producer_loop,
};

const TOPIC: &str = "propdefs-lull-drain-topic";
const DRAIN_SECS: u64 = 1;

fn test_lifecycle_handle() -> lifecycle::Handle {
    let mut manager = lifecycle::Manager::builder("test").build();
    manager.register("producer", lifecycle::ComponentOptions::new())
}

// A partial compaction batch has to reach the channel once its partition goes quiet. The loop only
// re-evaluates its flush condition when it wakes, so without the timer arm it parks in
// json_recv() after consuming an event and the batch sits there until traffic resumes.
//
// Two details make this test actually exercise that path rather than passing by accident.
// compaction_batch_size is far above one event's worth of updates, so size can never trigger the
// flush. And the assertion is on a *second* event, produced after the first batch has drained:
// the first event arrives while the consumer is still joining the group, several seconds after
// `last_send` was initialised, so its flush check passes on elapsed time alone and proves nothing.
// By the second event the consumer is warm and `last_send` was just reset, so elapsed is well
// under the drain interval and only the timer can get that batch out.
#[tokio::test]
async fn test_producer_flushes_a_partial_batch_when_events_stop_arriving() {
    let (cluster, producer) = common_kafka::test::create_mock_kafka().await;
    cluster.create_topic(TOPIC, 1, 1).expect("create topic");

    let mut config = Config::init_with_defaults().unwrap();
    config.kafka.kafka_hosts = cluster.bootstrap_servers();
    config.consumer.kafka_consumer_topic = TOPIC.to_string();
    config.consumer.kafka_consumer_group = "propdefs-lull-drain-group".to_string();
    config.consumer.kafka_consumer_offset_reset = "earliest".to_string();
    config.compaction_batch_size = 10_000;
    config.producer_drain_interval_secs = DRAIN_SECS;

    let send = |event: &'static str| {
        let payload = json!({
            "team_id": 111,
            "project_id": 111,
            "event": event,
            "properties": r#"{"$browser":"Chrome"}"#,
        })
        .to_string();
        let producer = producer.clone();
        async move {
            producer
                .send_result(FutureRecord::to(TOPIC).key("k").payload(&payload))
                .expect("enqueue")
                .await
                .expect("delivery")
                .expect("delivered");
        }
    };

    let consumer = SingleTopicConsumer::new(config.kafka.clone(), config.consumer.clone()).unwrap();
    let cache = Arc::new(Cache::new(1000, 1000, 1000));
    let (tx, mut rx) = measuring_channel::<Update>(1000);

    let handle = test_lifecycle_handle();
    let loop_task = tokio::spawn(update_producer_loop(
        config.clone(),
        consumer,
        cache,
        tx,
        handle.clone(),
    ));

    // First event: gets the consumer joined and the batch drained once, which resets `last_send`.
    send("$pageview").await;
    await_event_definition(&mut rx, "$pageview").await;

    // Second event, on a warm consumer. Nothing else will arrive, so the timer is the only thing
    // that can flush this one.
    send("$identify").await;
    await_event_definition(&mut rx, "$identify").await;

    // Drop the consumer inside the task. Left running, its drop lands on runtime teardown, where
    // librdkafka's synchronous close adds ~45s. Cancel the token directly rather than calling
    // request_shutdown(): that routes through the lifecycle Manager, which this test doesn't run.
    handle.shutdown_token().cancel();
    tokio::time::timeout(Duration::from_secs(30), loop_task)
        .await
        .expect("producer loop did not observe the shutdown signal")
        .expect("producer loop panicked");
}

// Reads until the named event's definition shows up. The compaction batch is an AHashSet, so a
// flush delivers its updates in arbitrary order, and one event yields property rows alongside the
// definition. The timeout is generous against mock-broker startup while staying far below the
// point where a missing timer arm could be mistaken for slowness.
async fn await_event_definition(
    rx: &mut property_defs_rs::measuring_channel::MeasuringReceiver<Update>,
    event: &str,
) {
    let deadline = Duration::from_secs(30);
    let found = tokio::time::timeout(deadline, async {
        loop {
            let update = rx.recv().await.expect("producer channel closed");
            if matches!(&update, Update::Event(ed) if ed.name == event && ed.team_id == 111) {
                return;
            }
        }
    })
    .await;

    assert!(
        found.is_ok(),
        "no event definition for {event} was flushed within {deadline:?}"
    );
}
