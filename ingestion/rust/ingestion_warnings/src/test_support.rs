//! Test doubles for [`crate::WarningEmitter`] and
//! [`crate::RowWarningEmitter`], available to downstream crates' dev-tests
//! (which is why this module is not `#[cfg(test)]`-gated).

use std::sync::Mutex;
use std::time::Duration;

use serde_json::{Map, Value};

use crate::registry::WarningType;
use crate::serializer::Warning;
use crate::{RowWarningEmitter, WarningEmitter, WarningSource};

/// One captured [`WarningEmitter::emit`] call.
#[derive(Debug, Clone, PartialEq)]
pub struct EmittedWarning {
    pub token: String,
    pub source: WarningSource,
    pub warning: WarningType,
    pub extra_details: Map<String, Value>,
    pub count: u64,
}

/// Emitter that records every call for assertions. No throttling, no I/O.
#[derive(Default)]
pub struct CollectingEmitter {
    emitted: Mutex<Vec<EmittedWarning>>,
}

impl CollectingEmitter {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn emitted(&self) -> Vec<EmittedWarning> {
        self.emitted.lock().expect("emitter mutex poisoned").clone()
    }
}

impl WarningEmitter for CollectingEmitter {
    fn emit(
        &self,
        token: String,
        source: WarningSource,
        warning: WarningType,
        extra_details: Map<String, Value>,
        count: u64,
    ) {
        self.emitted
            .lock()
            .expect("emitter mutex poisoned")
            .push(EmittedWarning {
                token,
                source,
                warning,
                extra_details,
                count,
            });
    }

    fn flush(&self, _timeout: Duration) {}
}

#[derive(Debug, Clone, PartialEq)]
pub struct EmittedRow {
    pub team_id: i64,
    pub scope: String,
    pub source: WarningSource,
    pub warning: WarningType,
    pub row: Value,
}

impl EmittedRow {
    pub fn details(&self) -> Value {
        serde_json::from_str(
            self.row["details"]
                .as_str()
                .expect("details is a JSON string"),
        )
        .expect("details parses")
    }
}

#[derive(Default)]
pub struct CollectingRowEmitter {
    rows: Mutex<Vec<EmittedRow>>,
}

impl CollectingRowEmitter {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn rows(&self) -> Vec<EmittedRow> {
        self.rows
            .lock()
            .expect("row emitter mutex poisoned")
            .clone()
    }

    pub fn clear(&self) {
        self.rows
            .lock()
            .expect("row emitter mutex poisoned")
            .clear();
    }
}

impl RowWarningEmitter for CollectingRowEmitter {
    fn emit(&self, team_id: i64, scope: &str, source: WarningSource, warning: Warning) {
        let warning_type = warning.warning_type();
        self.rows
            .lock()
            .expect("row emitter mutex poisoned")
            .push(EmittedRow {
                team_id,
                scope: scope.to_string(),
                source,
                warning: warning_type,
                row: warning.into_row(team_id, source),
            });
    }

    fn flush(&self, _timeout: Duration) {}
}
