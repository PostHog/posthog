use std::path::Path;

use anyhow::{anyhow, Result};

/// Info extracted from an Info.plist file
#[derive(Debug, Clone, Default, serde::Serialize)]
pub struct PlistInfo {
    /// CFBundleIdentifier (e.g., com.example.app)
    #[serde(rename = "CFBundleIdentifier")]
    pub bundle_identifier: Option<String>,
    /// CFBundleShortVersionString (e.g., 1.2.3)
    #[serde(rename = "CFBundleShortVersionString")]
    pub short_version: Option<String>,
    /// CFBundleVersion (e.g., 42)
    #[serde(rename = "CFBundleVersion")]
    pub bundle_version: Option<String>,
    /// CFBundleDevelopmentRegion (e.g., English, en)
    #[serde(rename = "CFBundleDevelopmentRegion")]
    pub development_region: Option<String>,
}

impl PlistInfo {
    /// Extract version info from an Info.plist file path
    pub fn from_plist(plist_path: &Path) -> Result<Self> {
        if !plist_path.exists() {
            anyhow::bail!("Info.plist not found at {}", plist_path.display());
        }

        let plist = plist::Value::from_file(plist_path)
            .map_err(|error| anyhow!("Failed to parse Info.plist: {error}"))?;
        let dictionary = plist
            .as_dictionary()
            .ok_or_else(|| anyhow!("Info.plist is not a dictionary"))?;

        Ok(Self {
            bundle_identifier: plist_string(dictionary, "CFBundleIdentifier"),
            short_version: plist_string(dictionary, "CFBundleShortVersionString"),
            bundle_version: plist_string(dictionary, "CFBundleVersion"),
            development_region: plist_string(dictionary, "CFBundleDevelopmentRegion"),
        })
    }

    pub fn resolve_release_fields<F>(mut self, environment: F) -> Self
    where
        F: Fn(&str) -> Option<String>,
    {
        self.bundle_identifier =
            resolve_build_setting_value(self.bundle_identifier.as_deref(), &environment)
                .or_else(|| environment_value("PRODUCT_BUNDLE_IDENTIFIER", &environment));
        self.short_version =
            resolve_build_setting_value(self.short_version.as_deref(), &environment)
                .or_else(|| environment_value("MARKETING_VERSION", &environment));
        self.bundle_version =
            resolve_build_setting_value(self.bundle_version.as_deref(), &environment)
                .or_else(|| environment_value("CURRENT_PROJECT_VERSION", &environment));
        self
    }
}

fn plist_string(dictionary: &plist::Dictionary, key: &str) -> Option<String> {
    dictionary
        .get(key)
        .and_then(plist::Value::as_string)
        .map(String::from)
}

fn environment_value<F>(name: &str, environment: &F) -> Option<String>
where
    F: Fn(&str) -> Option<String>,
{
    environment(name).and_then(|value| literal_value(&value))
}

fn resolve_build_setting_value<F>(value: Option<&str>, environment: &F) -> Option<String>
where
    F: Fn(&str) -> Option<String>,
{
    let value = value?;
    if let Some(variable) = exact_build_setting_reference(value) {
        return environment_value(variable, environment);
    }
    literal_value(value)
}

fn exact_build_setting_reference(value: &str) -> Option<&str> {
    let variable = value
        .strip_prefix("$(")
        .and_then(|value| value.strip_suffix(')'))
        .or_else(|| {
            value
                .strip_prefix("${")
                .and_then(|value| value.strip_suffix('}'))
        })?;

    (!variable.is_empty()
        && variable
            .bytes()
            .all(|character| character.is_ascii_alphanumeric() || character == b'_'))
    .then_some(variable)
}

fn literal_value(value: &str) -> Option<String> {
    (!value.is_empty() && !value.contains("$(") && !value.contains("${")).then(|| value.to_string())
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use super::*;

    #[test]
    fn resolves_only_literal_values_and_exact_build_setting_references() {
        let environment = HashMap::from([
            ("VERSION".to_string(), "1.2.3".to_string()),
            ("BUILD".to_string(), "42".to_string()),
            ("INDIRECT".to_string(), "$(VERSION)".to_string()),
        ]);
        let lookup = |name: &str| environment.get(name).cloned();
        let cases = [
            (Some("1.2.3"), Some("1.2.3")),
            (Some("$(VERSION)"), Some("1.2.3")),
            (Some("${BUILD}"), Some("42")),
            (Some("$(MISSING)"), None),
            (Some("v$(VERSION)"), None),
            (Some("${VERSION}-release"), None),
            (Some("$(INDIRECT)"), None),
            (Some(""), None),
            (None, None),
        ];

        for (value, expected) in cases {
            assert_eq!(
                resolve_build_setting_value(value, &lookup).as_deref(),
                expected,
                "value={value:?}"
            );
        }
    }

    #[test]
    fn falls_back_to_xcode_release_environment_values() {
        let info = PlistInfo {
            bundle_identifier: Some("$(APP_ID)".to_string()),
            short_version: Some("v$(VERSION)".to_string()),
            bundle_version: None,
            development_region: None,
        };
        let environment = HashMap::from([
            ("APP_ID".to_string(), "com.example.app".to_string()),
            ("MARKETING_VERSION".to_string(), "1.2.3".to_string()),
            ("CURRENT_PROJECT_VERSION".to_string(), "42".to_string()),
        ]);

        let resolved = info.resolve_release_fields(|name| environment.get(name).cloned());

        assert_eq!(
            resolved.bundle_identifier.as_deref(),
            Some("com.example.app")
        );
        assert_eq!(resolved.short_version.as_deref(), Some("1.2.3"));
        assert_eq!(resolved.bundle_version.as_deref(), Some("42"));
    }
}
