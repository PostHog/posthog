from dataclasses import dataclass, field


@dataclass
class MonitoredPackage:
    """Configuration for an npm package to monitor for unauthorized releases."""

    npm_package: str
    github_repo: str
    workflow_names: list[str] = field(default_factory=lambda: ["Release", "Publish", "release", "publish"])
    time_window_minutes: int = 10


# Package to GitHub repo mapping (validated against npm registry 2024-11)
MONITORED_PACKAGES: list[MonitoredPackage] = [
    # Core JS SDKs - PostHog/posthog-js monorepo
    MonitoredPackage(npm_package="posthog-js", github_repo="PostHog/posthog-js"),
    MonitoredPackage(npm_package="posthog-node", github_repo="PostHog/posthog-js"),
    MonitoredPackage(npm_package="posthog-react-native", github_repo="PostHog/posthog-js"),
    MonitoredPackage(npm_package="@posthog/core", github_repo="PostHog/posthog-js"),
    MonitoredPackage(npm_package="@posthog/ai", github_repo="PostHog/posthog-js"),
    MonitoredPackage(npm_package="@posthog/nextjs-config", github_repo="PostHog/posthog-js"),
    MonitoredPackage(npm_package="@posthog/nuxt", github_repo="PostHog/posthog-js"),
    # Separate repos for specific packages
    MonitoredPackage(
        npm_package="posthog-react-native-session-replay", github_repo="PostHog/posthog-react-native-session-replay"
    ),
    MonitoredPackage(npm_package="@posthog/nextjs", github_repo="PostHog/posthog-js-lite"),
    # CLI tools - separate repos
    MonitoredPackage(npm_package="@posthog/cli", github_repo="PostHog/posthog"),
    MonitoredPackage(npm_package="@posthog/wizard", github_repo="PostHog/wizard"),
    # Main PostHog monorepo packages
    MonitoredPackage(npm_package="@posthog/plugin-server", github_repo="PostHog/posthog"),
    MonitoredPackage(npm_package="@posthog/icons", github_repo="PostHog/posthog"),
    MonitoredPackage(npm_package="@posthog/lemon-ui", github_repo="PostHog/posthog"),
    # Standalone UI package
    MonitoredPackage(npm_package="@posthog/hedgehog-mode", github_repo="PostHog/hedgehog-mode"),
    # rrweb packages - PostHog/posthog-rrweb fork
    MonitoredPackage(npm_package="@posthog/rrweb-player", github_repo="PostHog/posthog-rrweb"),
    MonitoredPackage(npm_package="@posthog/rrweb-record", github_repo="PostHog/posthog-rrweb"),
    MonitoredPackage(npm_package="@posthog/rrweb-replay", github_repo="PostHog/posthog-rrweb"),
    MonitoredPackage(npm_package="@posthog/rrweb-snapshot", github_repo="PostHog/posthog-rrweb"),
    MonitoredPackage(npm_package="@posthog/rrweb-utils", github_repo="PostHog/posthog-rrweb"),
    MonitoredPackage(npm_package="@posthog/rrdom", github_repo="PostHog/posthog-rrweb"),
    MonitoredPackage(npm_package="@posthog/react-rrweb-player", github_repo="PostHog/posthog-react-rrweb-player"),
    # Forked/utility packages
    MonitoredPackage(npm_package="@posthog/piscina", github_repo="PostHog/piscina"),
    MonitoredPackage(npm_package="@posthog/clickhouse", github_repo="PostHog/node-clickhouse"),
    MonitoredPackage(npm_package="@posthog/siphash", github_repo="PostHog/siphash-js"),
    # Example/test packages
    MonitoredPackage(npm_package="posthog-plugin-hello-world", github_repo="PostHog/posthog-plugin-hello-world"),
]


@dataclass
class NpmReleaseMonitorState:
    """Persisted state for the monitor - tracks last seen versions."""

    last_checked_versions: dict[str, str] = field(default_factory=dict)
    last_run_timestamp: str | None = None


def get_packages_by_repo() -> dict[str, list[MonitoredPackage]]:
    """Group monitored packages by their GitHub repo for efficient API calls."""
    by_repo: dict[str, list[MonitoredPackage]] = {}
    for pkg in MONITORED_PACKAGES:
        if pkg.github_repo not in by_repo:
            by_repo[pkg.github_repo] = []
        by_repo[pkg.github_repo].append(pkg)
    return by_repo
