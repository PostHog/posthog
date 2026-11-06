use serde::{Deserialize, Serialize};

use crate::error_tracking::FrameData;

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct ExceptionData {
    pub exception_type: String,
    pub exception_value: String,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub frames: Vec<FrameData>,
}
