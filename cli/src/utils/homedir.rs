use std::{ffi::OsString, path::PathBuf};

use anyhow::{Context, Error};

// IF `POSTHOG_HOME` is set, use that, otherwise use $HOME/.posthog
pub fn posthog_home_dir_if_available() -> Option<PathBuf> {
    posthog_home_dir().ok()
}

pub fn posthog_home_dir() -> Result<PathBuf, Error> {
    resolve_posthog_home(std::env::var_os("POSTHOG_HOME"), dirs::home_dir())
}

fn resolve_posthog_home(
    posthog_home: Option<OsString>,
    home: Option<PathBuf>,
) -> Result<PathBuf, Error> {
    if let Some(posthog_home) = posthog_home {
        return Ok(PathBuf::from(posthog_home));
    }

    let mut home = home.context(
        "Could not find a home directory. Set POSTHOG_HOME to a writable directory, \
         or set POSTHOG_CLI_API_KEY and POSTHOG_CLI_PROJECT_ID to authenticate without one",
    )?;
    home.push(".posthog");
    Ok(home)
}

pub fn ensure_homedir_exists() -> Result<(), Error> {
    let home = posthog_home_dir()?;
    std::fs::create_dir_all(&home).context(format!("While trying to create directory {home:?}"))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resolve_posthog_home_errors_with_hint_when_no_home_is_found() {
        let err = resolve_posthog_home(None, None).unwrap_err().to_string();
        assert!(err.contains("POSTHOG_HOME"));
        assert!(err.contains("POSTHOG_CLI_API_KEY"));
    }
}
