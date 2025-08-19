use std::path::PathBuf;

use anyhow::{Context, Error};

// IF `POSTHOG_HOME` is set, use that, otherwise use $HOME/.posthog
pub fn posthog_home_dir() -> PathBuf {
    match std::env::var("POSTHOG_HOME") {
        Ok(home) => PathBuf::from(home),
        Err(_) => {
            let mut home = dirs::home_dir().expect("Could not find home directory");
            home.push(".posthog");
            home
        }
    }
}

pub fn ensure_homedir_exists() -> Result<(), Error> {
    let home = posthog_home_dir();
    std::fs::create_dir_all(&home).context(format!("While trying to create directory {home:?}"))?;
    Ok(())
}
