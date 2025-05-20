// Random utils for sending metrics to PostHog

use std::thread::JoinHandle;

use posthog_rs::Event;
use tracing::{debug, warn};

pub fn init_posthog() {
    // This is pulled at compile time, not runtime - we set it at build.
    let Some(token) = option_env!("POSTHOG_API_TOKEN") else {
        warn!("Posthog api token not set at build time - is this a debug build?");
        return;
    };

    let ph_config = posthog_rs::ClientOptionsBuilder::default()
        .api_key(token.to_string())
        .request_timeout_seconds(5) // It's a CLI, 5 seconds is an eternity
        .build()
        .expect("Building PH config succeeds");

    posthog_rs::init_global(ph_config).expect("Initializing PostHog client");
}

pub fn capture_command_invoked(
    command: impl AsRef<str>,
    env_id: Option<impl AsRef<str>>,
) -> JoinHandle<()> {
    let event_name = "posthog cli command run".to_string();
    let mut event = Event::new_anon(event_name);

    event
        .insert_prop("command_name", command.as_ref())
        .expect("Inserting command prop succeeds");

    if let Some(env_id) = env_id {
        event
            .insert_prop("env_id", env_id.as_ref())
            .expect("Inserting env_id prop succeeds");
    }

    spawn_capture(event)
}

fn spawn_capture(event: Event) -> JoinHandle<()> {
    std::thread::spawn(move || {
        debug!("Capturing event");
        let res = posthog_rs::capture(event); // Purposefully ignore errors here
        if let Err(err) = res {
            debug!("Failed to capture event: {:?}", err);
        } else {
            debug!("Event captured successfully");
        }
    })
}
