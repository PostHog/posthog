// Test cases for the capture-config-via-config-resolution rule.

use envconfig::Envconfig;

fn parses_config_directly() -> Config {
    // ruleid: capture-config-via-config-resolution
    Config::init_from_env().expect("Invalid configuration:")
}

fn parses_config_from_a_snapshot(env: &HashMap<String, String>) -> Config {
    // ruleid: capture-config-via-config-resolution
    envconfig::Envconfig::init_from_hashmap(env).unwrap()
}

fn parses_via_self() -> Result<Self, envconfig::Error> {
    // ruleid: capture-config-via-config-resolution
    Self::init_from_env()
}

fn parses_via_qualified_trait_syntax() -> Config {
    // ruleid: capture-config-via-config-resolution
    <Config as Envconfig>::init_from_env().unwrap()
}

fn resolves_through_the_choke_point() -> anyhow::Result<Config> {
    // ok: capture-config-via-config-resolution
    let resolved = crate::config_resolution::resolve(&std::env::vars().collect())?;
    Ok(resolved.config().clone())
}

fn resolves_around_a_built_config(config: Config) -> anyhow::Result<Resolved> {
    // ok: capture-config-via-config-resolution
    crate::config_resolution::resolve_with_config(config, &std::env::vars().collect())
}

// Inline unit tests build configs directly on purpose.
#[cfg(test)]
mod tests {
    use super::*;

    fn test_config(env: &HashMap<String, String>) -> Config {
        // ok: capture-config-via-config-resolution
        envconfig::Envconfig::init_from_hashmap(env).expect("test config")
    }

    #[test]
    fn a_test_that_builds_its_own_config() {
        // ok: capture-config-via-config-resolution
        let config: Config = Config::init_from_env().unwrap();
        assert!(!config.print_sink);
    }
}
