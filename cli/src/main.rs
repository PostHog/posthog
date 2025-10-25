use posthog_cli::cmd;
use rayon::ThreadPoolBuilder;
use tracing::info;

fn main() {
    let subscriber = tracing_subscriber::fmt()
        .with_writer(std::io::stderr)
        .with_env_filter(
            tracing_subscriber::EnvFilter::builder()
                .with_default_directive(tracing::Level::INFO.into())
                .from_env_lossy(),
        )
        .finish();

    // Init the rayon thread pool
    ThreadPoolBuilder::new()
        .num_threads(10)
        .build_global()
        .expect("We successfully install a global thread pool");

    tracing::subscriber::set_global_default(subscriber).expect("Failed to set tracing subscriber");

    match cmd::Cli::run() {
        Ok(_) => info!("All done, happy hogging!"),
        Err(_) => {
            std::process::exit(1);
        }
    }
}
