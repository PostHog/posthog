use std::path::PathBuf;

use anyhow::{Context, Error};

// IF `POSTHOG_HOME` is set, use that, otherwise use $HOME/.posthog
pub fn posthog_home_dir_if_available() -> Option<PathBuf> {
    if let Some(home) = std::env::var_os("POSTHOG_HOME") {
        return Some(PathBuf::from(home));
    }

    let mut home = dirs::home_dir()?;
    home.push(".posthog");
    Some(home)
}

pub fn posthog_home_dir() -> PathBuf {
    posthog_home_dir_if_available().expect("Could not find home directory")
}

pub fn ensure_homedir_exists() -> Result<(), Error> {
    let home = posthog_home_dir();
    std::fs::create_dir_all(&home).context(format!("While trying to create directory {home:?}"))?;
    Ok(())
}
