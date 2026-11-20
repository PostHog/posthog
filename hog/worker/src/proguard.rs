// ProGuard and R8 mapping files, checked with the proguard crate and packed with the
// posthog-symbol-data crate as posthog-cli does.

use posthog_symbol_data::{write_symbol_data, ProguardMapping};
use serde::Serialize;
use std::path::Path;

use crate::{node, upload};

#[derive(Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Invalid {
    NotUtf8,
    NotAMapping,
}

#[derive(Serialize)]
#[serde(untagged)]
pub enum Built {
    Invalid {
        invalid: Invalid,
    },
    #[serde(rename_all = "camelCase")]
    Container {
        content_hash: String,
        size: usize,
    },
}

// Whether a class is followed by a field or a method among the first records. The check works on
// bytes, so a file that is not UTF-8 can still pass it.
pub fn is_valid_mapping(bytes: &[u8]) -> bool {
    proguard::ProguardMapping::new(bytes).is_valid()
}

// The payload is the file as it is on disk: a byte order mark or CRLF stays, because posthog-cli
// uploads and hashes the bytes unchanged. `out` is None in a dry run, which writes nothing.
pub fn build(path: &Path, out: Option<&Path>) -> Result<Built, String> {
    let Ok(content) = String::from_utf8(node::read(path)?) else {
        return Ok(Built::Invalid {
            invalid: Invalid::NotUtf8,
        });
    };
    if !is_valid_mapping(content.as_bytes()) {
        return Ok(Built::Invalid {
            invalid: Invalid::NotAMapping,
        });
    }

    let container =
        write_symbol_data(ProguardMapping { content }).map_err(|error| error.to_string())?;
    if let Some(out) = out {
        upload::write_container(out, &container).map_err(|error| error.to_string())?;
    }

    Ok(Built::Container {
        content_hash: upload::content_hash([&container]),
        size: container.len(),
    })
}
