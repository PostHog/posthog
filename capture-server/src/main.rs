use std::env;
use std::net::SocketAddr;

use capture::{router, sink, time};

#[tokio::main]
async fn main() {
    let use_print_sink = env::var("PRINT_SINK").is_ok();
    let address = env::var("ADDRESS").unwrap_or(String::from("127.0.0.1:3000"));

    let app = if use_print_sink {
        router::router(time::SystemTime {}, sink::PrintSink {}, true)
    } else {
        let brokers = env::var("KAFKA_BROKERS").expect("Expected KAFKA_BROKERS");
        let topic = env::var("KAFKA_TOPIC").expect("Expected KAFKA_TOPIC");

        let sink = sink::KafkaSink::new(topic, brokers).unwrap();

        router::router(time::SystemTime {}, sink, true)
    };

    // initialize tracing

    tracing_subscriber::fmt::init();
    // run our app with hyper
    // `axum::Server` is a re-export of `hyper::Server`

    tracing::info!("listening on {}", address);

    axum::Server::bind(&address.parse().unwrap())
        .serve(app.into_make_service_with_connect_info::<SocketAddr>())
        .await
        .unwrap();
}
