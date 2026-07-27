use anyhow::{Context, Error};
use std::collections::HashMap;
use std::path::Path;

// Credential values are read literally — no $VAR/${VAR} interpolation — so a credentials file
// can't pull a secret out of the process environment and pair it with a host of its choosing.
pub(crate) fn load_dotenv(path: &Path) -> Result<HashMap<String, String>, Error> {
    let contents = std::fs::read_to_string(path)
        .with_context(|| format!("While trying to read env file {}", path.display()))?;
    let mut map = HashMap::new();
    for (i, raw) in contents.lines().enumerate() {
        let line = raw.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let (key, value) = line.split_once('=').with_context(|| {
            format!(
                "Malformed line {} in env file {}: expected KEY=VALUE",
                i + 1,
                path.display()
            )
        })?;
        let key = key.trim();
        if key.is_empty() {
            anyhow::bail!(
                "Malformed line {} in env file {}: empty key",
                i + 1,
                path.display()
            );
        }
        map.insert(key.to_string(), unquote(value.trim()).to_string());
    }
    Ok(map)
}

fn unquote(value: &str) -> &str {
    let bytes = value.as_bytes();
    if bytes.len() >= 2 {
        let quote = bytes[0];
        if (quote == b'"' || quote == b'\'') && bytes[bytes.len() - 1] == quote {
            return &value[1..value.len() - 1];
        }
    }
    value
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    #[test]
    fn load_dotenv_parses_file() {
        let mut f = tempfile::NamedTempFile::new().unwrap();
        writeln!(f, "POSTHOG_CLI_API_KEY=phx_from_file").unwrap();
        writeln!(f, "POSTHOG_CLI_PROJECT_ID=99").unwrap();
        let map = load_dotenv(f.path()).unwrap();
        assert_eq!(map.get("POSTHOG_CLI_API_KEY").unwrap(), "phx_from_file");
        assert_eq!(map.get("POSTHOG_CLI_PROJECT_ID").unwrap(), "99");
    }

    #[test]
    fn load_dotenv_errors_when_missing() {
        let err = load_dotenv(Path::new("/definitely/not/a/real/path/.env")).unwrap_err();
        assert!(err.to_string().contains("env file"));
    }

    #[test]
    fn load_dotenv_strips_quotes_and_comments() {
        let mut f = tempfile::NamedTempFile::new().unwrap();
        writeln!(f, "# a comment").unwrap();
        writeln!(f).unwrap();
        writeln!(f, "POSTHOG_CLI_API_KEY=\"phx_quoted\"").unwrap();
        writeln!(f, "POSTHOG_CLI_HOST='https://eu.posthog.com'").unwrap();
        let map = load_dotenv(f.path()).unwrap();
        assert_eq!(map.get("POSTHOG_CLI_API_KEY").unwrap(), "phx_quoted");
        assert_eq!(
            map.get("POSTHOG_CLI_HOST").unwrap(),
            "https://eu.posthog.com"
        );
    }

    #[test]
    fn load_dotenv_does_not_interpolate_process_env() {
        let key = "POSTHOG_CLI_DOTENV_TEST_INTERP";
        std::env::set_var(key, "secret_from_process");

        let mut f = tempfile::NamedTempFile::new().unwrap();
        writeln!(f, "VALUE=${{{key}}}").unwrap();
        let map = load_dotenv(f.path()).unwrap();
        assert_eq!(map.get("VALUE").unwrap(), &format!("${{{key}}}"));

        std::env::remove_var(key);
    }
}
