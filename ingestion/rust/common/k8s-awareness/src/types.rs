use serde::{Deserialize, Serialize};
use std::fmt;

/// What kind of K8s controller manages the consumer/pod fleet.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum ControllerKind {
    Deployment,
    StatefulSet,
}

impl fmt::Display for ControllerKind {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Deployment => write!(f, "Deployment"),
            Self::StatefulSet => write!(f, "StatefulSet"),
        }
    }
}

/// Identifies a specific controller instance (e.g., "Deployment/kafka-dedup").
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct ControllerRef {
    pub kind: ControllerKind,
    pub name: String,
}

impl fmt::Display for ControllerRef {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}/{}", self.kind, self.name)
    }
}

/// The coordinator's understanding of what K8s is doing with a controller's fleet.
#[derive(Debug, Clone)]
pub struct ClusterIntent {
    /// Current desired replica count.
    pub desired_replicas: u32,
    /// Previous desired replica count (to detect downscale).
    pub previous_replicas: Option<u32>,
    /// Whether a rollout is in progress.
    pub rollout_in_progress: bool,
    /// The current generation hash (pod-template-hash or controller-revision-hash).
    pub current_generation: String,
    /// The target generation hash (differs from current during rollout).
    pub target_generation: Option<String>,
}

/// Why a member is departing, as determined by correlating K8s state.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DepartureReason {
    /// Pod is being replaced by a new version.
    Rollout,
    /// Replica count was reduced; this pod will not come back.
    Downscale,
    /// Pod crashed or unknown disruption; K8s will restart it.
    Crash,
    /// K8s awareness unavailable; fall back to current behavior.
    Unknown,
}

impl fmt::Display for DepartureReason {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Rollout => write!(f, "rollout"),
            Self::Downscale => write!(f, "downscale"),
            Self::Crash => write!(f, "crash"),
            Self::Unknown => write!(f, "unknown"),
        }
    }
}

/// Information about a pod's relationship to its K8s controller.
#[derive(Debug, Clone)]
pub struct PodInfo {
    pub controller: ControllerRef,
    /// pod-template-hash (Deployment) or controller-revision-hash (StatefulSet).
    pub generation: String,
}
