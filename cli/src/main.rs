use posthog_cli::{cmd, utils::posthog::init_posthog};
use rayon::ThreadPoolBuilder;
use tracing::{error, info};

fn main() {
    let subscriber = tracing_subscriber::fmt()
        .with_writer(std::io::stderr)
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_default_env()
                .add_directive(tracing::Level::INFO.into()),
        )
        .finish();

    // Init the rayon thread pool
    ThreadPoolBuilder::new()
        .num_threads(10)
        .build_global()
        .expect("We successfully install a global thread pool");

    tracing::subscriber::set_global_default(subscriber).expect("Failed to set tracing subscriber");

    init_posthog();

    match cmd::Cli::run() {
        Ok(_) => info!("All done, happy hogging!"),
        Err(e) => {
            let msg = match e.exception_id {
                Some(id) => format!("Oops! {} (ID: {})", e.inner, id),
                None => format!("Oops! {:?}", e.inner),
            };
            error!(msg);
            std::process::exit(1);
        }
    }
}
