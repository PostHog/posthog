use axum::{extract::State, routing::get, Router};
use common_metrics::setup_metrics_routes;
use cyclotron_janitor::{config::Config, janitor::Janitor};
use envconfig::Envconfig;
use eyre::Result;
use health::{HealthHandle, HealthRegistry};
use std::{future::ready, time::Duration};
use tracing::{error, info};

common_alloc::used!();

async fn cleanup_loop(janitor: Janitor, livenes: HealthHandle, interval_secs: u64) -> Result<()> {
    let mut interval = tokio::time::interval(Duration::from_secs(interval_secs));

    loop {
        interval.tick().await;

        if let Err(e) = janitor.run_once().await {
            // don't bother reporting unhealthy - a few times around this loop will put us in a stalled state
            error!("janitor failed cleanup with: {}", e);
        } else {
            livenes.report_healthy().await;
        }
    }
}

async fn listen(app: Router, bind: String) -> Result<()> {
    let listener = tokio::net::TcpListener::bind(bind).await?;

    axum::serve(listener, app).await?;

    Ok(())
}

// For axums state stuff
#[derive(Clone)]
struct JanitorId(pub String);

pub fn app(liveness: HealthRegistry, janitor_id: String) -> Router {
    Router::new()
        .route("/", get(index))
        .route("/_readiness", get(index))
        .route("/_liveness", get(move || ready(liveness.get_status())))
        .with_state(JanitorId(janitor_id))
}

async fn index(State(janitor_id): State<JanitorId>) -> String {
    format!("cyclotron janitor {}", janitor_id.0)
}

#[tokio::main]
async fn main() {
    let config = Config::init_from_env().expect("failed to load configuration from env");
    tracing_subscriber::fmt::init();

    let liveness = HealthRegistry::new("liveness");

    let janitor_config = config.get_janitor_config();

    let janitor_id = janitor_config.settings.id.clone();
    let bind = format!("{}:{}", config.host, config.port);

    info!(
        "Starting janitor with ID {:?}, listening at {}",
        janitor_id, bind
    );

    let janitor = Janitor::new(janitor_config, &liveness)
        .await
        .expect("failed to create janitor");

    janitor.run_migrations().await;

    let janitor_liveness = liveness
        .register(
            "janitor".to_string(),
            Duration::from_secs(config.cleanup_interval_secs * 4),
        )
        .await;

    let janitor_loop = tokio::spawn(cleanup_loop(
        janitor,
        janitor_liveness,
        config.cleanup_interval_secs,
    ));

    let app = setup_metrics_routes(app(liveness, janitor_id));
    let http_server = tokio::spawn(listen(app, bind));

    tokio::select! {
        res = janitor_loop => {
            error!("janitor loop exited");
            if let Err(e) = res {
                error!("janitor failed with: {}", e)
            }
        }
        res = http_server => {
            error!("http server exited");
            if let Err(e) = res {
                error!("server failed with: {}", e)
            }
        }
    }

    info!("exiting");
}
