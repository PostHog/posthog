use std::env;
use std::panic;
use std::sync::Once;

use envconfig::Envconfig;
use pyroscope::backend::jemalloc::jemalloc_backend;
use pyroscope::backend::{
    pprof_backend, BackendConfig, BackendImpl, BackendUninitialized, PprofConfig,
};
use pyroscope::pyroscope::{PyroscopeAgentBuilder, PyroscopeAgentRunning};
use pyroscope::PyroscopeAgent;

static PANIC_HOOK_INSTALLED: Once = Once::new();

const SPY_NAME: &str = "pyroscope-rs";

/// K8s metadata environment variables for Pyroscope tags
const K8S_TAG_ENV_VARS: &[(&str, &str)] = &[
    ("namespace", "K8S_NAMESPACE"),
    ("pod", "K8S_POD_NAME"),
    ("node", "K8S_NODE_NAME"),
    ("pod_template_hash", "K8S_POD_TEMPLATE_HASH"),
    ("app_instance", "K8S_APP_INSTANCE"),
    ("app", "K8S_APP"),
    ("container", "K8S_CONTAINER_NAME"),
    ("controller_type", "K8S_CONTROLLER_TYPE"),
    // No service_name here: pyroscope 2.x already sets it from the application
    // name, and the server rejects profiles with a duplicate label (HTTP 400).
];

#[derive(Envconfig, Clone, Debug)]
pub struct ContinuousProfilingConfig {
    #[envconfig(default = "false")]
    pub continuous_profiling_enabled: bool,

    /// Also push jemalloc heap profiles (profile type "memory"). Requires jemalloc
    /// profiling to be active at process start, e.g.
    /// `_RJEM_MALLOC_CONF=prof:true,prof_active:true,lg_prof_sample:19`.
    #[envconfig(default = "false")]
    pub continuous_profiling_memory_enabled: bool,

    #[envconfig(default = "")]
    pub pyroscope_server_address: String,

    #[envconfig(default = "")]
    pub pyroscope_application_name: String,

    #[envconfig(default = "100")]
    pub pyroscope_sample_rate: u32,
}

/// A running Pyroscope agent handle. Keep this alive for the duration of profiling.
pub type RunningAgent = PyroscopeAgent<PyroscopeAgentRunning>;

/// The running profiling agents. Keep this alive for the duration of profiling;
/// dropping it stops all profiling.
pub struct RunningAgents {
    _cpu: RunningAgent,
    _memory: Option<RunningAgent>,
}

impl Default for ContinuousProfilingConfig {
    fn default() -> Self {
        Self {
            continuous_profiling_enabled: false,
            continuous_profiling_memory_enabled: false,
            pyroscope_server_address: String::new(),
            pyroscope_application_name: String::new(),
            pyroscope_sample_rate: 100,
        }
    }
}

/// Collect K8s metadata tags from environment variables.
fn collect_k8s_tags() -> Vec<(String, String)> {
    let mut tags = vec![("src".to_string(), "SDK".to_string())];
    for (tag_name, env_var) in K8S_TAG_ENV_VARS {
        match env::var(env_var) {
            Ok(value) if !value.is_empty() => {
                tags.push(((*tag_name).to_string(), value));
            }
            _ => {
                tracing::warn!(
                    tag_name = %tag_name,
                    env_var = %env_var,
                    "K8s tag not set (env var is empty)"
                );
            }
        }
    }
    tags
}

/// Install a panic hook that logs panics from pyroscope threads without aborting.
///
/// The pyroscope library spawns internal threads that may panic (e.g., during
/// GZIP compression or network errors). By default, panics in threads will
/// print to stderr but won't abort the process. However, we install a custom
/// hook to ensure we log these panics properly and they don't interfere with
/// the main application.
fn install_panic_safe_hook() {
    PANIC_HOOK_INSTALLED.call_once(|| {
        let default_hook = panic::take_hook();
        panic::set_hook(Box::new(move |panic_info| {
            let thread = std::thread::current();
            let thread_name = thread.name().unwrap_or("<unnamed>");

            // Check if this is a pyroscope-related thread by name
            let is_pyroscope_thread =
                thread_name.contains("pyroscope") || thread_name.contains("Pyroscope");

            if is_pyroscope_thread {
                // Log the panic but don't abort - let the thread die gracefully
                tracing::error!(
                    thread = %thread_name,
                    panic = %panic_info,
                    "Pyroscope thread panicked - profiling may be degraded but service continues"
                );
            } else {
                // For non-pyroscope threads, use the default behavior
                default_hook(panic_info);
            }
        }));
    });
}

impl ContinuousProfilingConfig {
    /// Initialize continuous profiling if enabled.
    ///
    /// Returns an `Option<RunningAgents>` that should be kept alive for the
    /// duration of the application. When dropped, the agents will stop profiling.
    ///
    /// A CPU profiling agent is always started. When
    /// `continuous_profiling_memory_enabled` is set, a second agent pushes
    /// jemalloc heap profiles; if that agent fails to start (typically because
    /// jemalloc profiling isn't active), the error is logged and CPU profiling
    /// continues alone.
    ///
    /// This function installs a panic hook to ensure that panics in pyroscope's
    /// internal threads don't crash the main application. The pyroscope library
    /// has some `.unwrap()` calls that can panic under certain conditions
    /// (e.g., GZIP compression failures, network errors).
    ///
    /// # Example
    ///
    /// ```ignore
    /// let config = ContinuousProfilingConfig::init_from_env()?;
    /// let _agents = config.start_agent()?;
    /// // Agents run until _agents is dropped
    /// ```
    pub fn start_agent(&self) -> Result<Option<RunningAgents>, ContinuousProfilingError> {
        if !self.continuous_profiling_enabled {
            tracing::info!("Continuous profiling is disabled");
            return Ok(None);
        }

        if self.pyroscope_server_address.is_empty() {
            tracing::warn!(
                "Continuous profiling is enabled but PYROSCOPE_SERVER_ADDRESS is empty, skipping"
            );
            return Ok(None);
        }

        // Install panic hook before starting pyroscope to catch any panics
        // from its internal threads
        install_panic_safe_hook();

        let tags = collect_k8s_tags();

        tracing::info!(
            server_address = %self.pyroscope_server_address,
            app_name = %self.pyroscope_application_name,
            sample_rate = %self.pyroscope_sample_rate,
            memory_enabled = %self.continuous_profiling_memory_enabled,
            tags = ?tags,
            "Starting continuous profiling"
        );

        let cpu_backend = pprof_backend(
            PprofConfig {
                sample_rate: self.pyroscope_sample_rate,
            },
            BackendConfig::default(),
        );
        let cpu = self.start_backend(cpu_backend, &tags)?;

        let memory = if self.continuous_profiling_memory_enabled {
            match self.start_backend(jemalloc_backend(), &tags) {
                Ok(agent) => Some(agent),
                Err(e) => {
                    tracing::error!(
                        error = %e,
                        "Failed to start memory profiling agent - check that jemalloc \
                         profiling is active (_RJEM_MALLOC_CONF=prof:true,prof_active:true); \
                         CPU profiling continues"
                    );
                    None
                }
            }
        } else {
            None
        };

        tracing::info!(
            memory_profiling = %memory.is_some(),
            "Continuous profiling agent started successfully"
        );

        Ok(Some(RunningAgents {
            _cpu: cpu,
            _memory: memory,
        }))
    }

    fn start_backend(
        &self,
        backend: BackendImpl<BackendUninitialized>,
        tags: &[(String, String)],
    ) -> Result<RunningAgent, ContinuousProfilingError> {
        // Convert tags to the format expected by pyroscope: Vec<(&str, &str)>
        let tags_refs: Vec<(&str, &str)> =
            tags.iter().map(|(k, v)| (k.as_str(), v.as_str())).collect();

        let agent = PyroscopeAgentBuilder::new(
            &self.pyroscope_server_address,
            &self.pyroscope_application_name,
            self.pyroscope_sample_rate,
            SPY_NAME,
            env!("CARGO_PKG_VERSION"),
            backend,
        )
        .tags(tags_refs)
        .build()
        .map_err(ContinuousProfilingError::Build)?;

        agent.start().map_err(ContinuousProfilingError::Start)
    }
}

#[derive(Debug, thiserror::Error)]
pub enum ContinuousProfilingError {
    #[error("Failed to build profiling agent: {0}")]
    Build(pyroscope::error::PyroscopeError),

    #[error("Failed to start profiling agent: {0}")]
    Start(pyroscope::error::PyroscopeError),
}
