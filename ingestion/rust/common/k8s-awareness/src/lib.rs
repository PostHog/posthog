mod detection;
mod discovery;
mod endpoints;
mod peers;
pub mod types;
mod watcher;

pub use detection::classify_departure;
pub use discovery::{
    discover_controller, get_pod, list_pods_by_selector, DiscoveredPod, DiscoveryError,
};
pub use endpoints::watch_service_members;
pub use peers::{PeerSet, PeerTracker};
pub use types::{ClusterIntent, ControllerKind, ControllerRef, DepartureReason, PodInfo};
pub use watcher::{K8sAwareness, K8sAwarenessError};
