from dataclasses import dataclass, field


@dataclass
class MonitoredPackage:
    """Configuration for an npm package to monitor for unauthorized releases."""

    npm_package: str
    github_repo: str
    workflow_names: list[str] = field(default_factory=lambda: ["Release", "Publish", "release", "publish"])
    time_window_minutes: int = 10


# Package to GitHub repo mapping
# TODO: Verify these mappings are correct
MONITORED_PACKAGES: list[MonitoredPackage] = [
    # Core JS SDKs - PostHog/posthog-js monorepo
    MonitoredPackage(npm_package="posthog-js", github_repo="PostHog/posthog-js"),
    MonitoredPackage(npm_package="posthog-node", github_repo="PostHog/posthog-js"),
    MonitoredPackage(npm_package="posthog-react-native", github_repo="PostHog/posthog-js"),
    MonitoredPackage(npm_package="posthog-react-native-session-replay", github_repo="PostHog/posthog-js"),
    MonitoredPackage(npm_package="@posthog/core", github_repo="PostHog/posthog-js"),
    MonitoredPackage(npm_package="@posthog/ai", github_repo="PostHog/posthog-js"),
    MonitoredPackage(npm_package="@posthog/nextjs", github_repo="PostHog/posthog-js"),
    MonitoredPackage(npm_package="@posthog/nextjs-config", github_repo="PostHog/posthog-js"),
    MonitoredPackage(npm_package="@posthog/nuxt", github_repo="PostHog/posthog-js"),
    # CLI tools
    MonitoredPackage(npm_package="@posthog/cli", github_repo="PostHog/posthog-js"),
    MonitoredPackage(npm_package="@posthog/wizard", github_repo="PostHog/posthog-js"),
    MonitoredPackage(npm_package="@posthog/agent", github_repo="PostHog/posthog-js"),
    # Plugin server
    MonitoredPackage(npm_package="@posthog/plugin-server", github_repo="PostHog/posthog"),
    # UI components
    MonitoredPackage(npm_package="@posthog/icons", github_repo="PostHog/posthog"),
    MonitoredPackage(npm_package="@posthog/lemon-ui", github_repo="PostHog/posthog"),
    MonitoredPackage(npm_package="@posthog/hedgehog-mode", github_repo="PostHog/hedgehog-mode"),
    # rrweb packages - likely PostHog/rrweb fork
    MonitoredPackage(npm_package="@posthog/rrweb", github_repo="PostHog/rrweb"),
    MonitoredPackage(npm_package="@posthog/rrweb-player", github_repo="PostHog/rrweb"),
    MonitoredPackage(npm_package="@posthog/rrweb-record", github_repo="PostHog/rrweb"),
    MonitoredPackage(npm_package="@posthog/rrweb-replay", github_repo="PostHog/rrweb"),
    MonitoredPackage(npm_package="@posthog/rrweb-snapshot", github_repo="PostHog/rrweb"),
    MonitoredPackage(npm_package="@posthog/rrweb-utils", github_repo="PostHog/rrweb"),
    MonitoredPackage(npm_package="@posthog/rrdom", github_repo="PostHog/rrweb"),
    MonitoredPackage(npm_package="@posthog/react-rrweb-player", github_repo="PostHog/rrweb"),
    # Plugins - likely in posthog-plugins repo or individual repos
    MonitoredPackage(npm_package="@posthog/plugin-contrib", github_repo="PostHog/posthog-plugin-contrib"),
    MonitoredPackage(npm_package="@posthog/customerio-plugin", github_repo="PostHog/posthog-plugins"),
    MonitoredPackage(npm_package="@posthog/event-sequence-timer-plugin", github_repo="PostHog/posthog-plugins"),
    MonitoredPackage(npm_package="@posthog/automatic-cohorts-plugin", github_repo="PostHog/posthog-plugins"),
    MonitoredPackage(npm_package="@posthog/first-time-event-tracker", github_repo="PostHog/posthog-plugins"),
    MonitoredPackage(npm_package="@posthog/ingestion-alert-plugin", github_repo="PostHog/posthog-plugins"),
    MonitoredPackage(npm_package="@posthog/pagerduty-plugin", github_repo="PostHog/posthog-plugins"),
    MonitoredPackage(npm_package="@posthog/kinesis-plugin", github_repo="PostHog/posthog-plugins"),
    MonitoredPackage(npm_package="@posthog/plugin-unduplicates", github_repo="PostHog/posthog-plugins"),
    MonitoredPackage(npm_package="@posthog/gitub-star-sync-plugin", github_repo="PostHog/posthog-plugins"),
    MonitoredPackage(npm_package="@posthog/github-release-tracking-plugin", github_repo="PostHog/posthog-plugins"),
    MonitoredPackage(npm_package="@posthog/geoip-plugin", github_repo="PostHog/posthog-plugins"),
    MonitoredPackage(npm_package="@posthog/maxmind-plugin", github_repo="PostHog/posthog-plugins"),
    MonitoredPackage(npm_package="@posthog/currency-normalization-plugin", github_repo="PostHog/posthog-plugins"),
    MonitoredPackage(npm_package="@posthog/databricks-plugin", github_repo="PostHog/posthog-plugins"),
    MonitoredPackage(npm_package="@posthog/url-normalizer-plugin", github_repo="PostHog/posthog-plugins"),
    MonitoredPackage(npm_package="@posthog/sendgrid-plugin", github_repo="PostHog/posthog-plugins"),
    MonitoredPackage(npm_package="@posthog/twitter-followers-plugin", github_repo="PostHog/posthog-plugins"),
    MonitoredPackage(npm_package="@posthog/taxonomy-plugin", github_repo="PostHog/posthog-plugins"),
    MonitoredPackage(npm_package="@posthog/snowflake-export-plugin", github_repo="PostHog/posthog-plugins"),
    MonitoredPackage(npm_package="@posthog/twilio-plugin", github_repo="PostHog/posthog-plugins"),
    MonitoredPackage(npm_package="@posthog/variance-plugin", github_repo="PostHog/posthog-plugins"),
    MonitoredPackage(npm_package="@posthog/zendesk-plugin", github_repo="PostHog/posthog-plugins"),
    MonitoredPackage(npm_package="@posthog/postgres-plugin", github_repo="PostHog/posthog-plugins"),
    MonitoredPackage(npm_package="@posthog/bitbucket-release-tracker", github_repo="PostHog/posthog-plugins"),
    MonitoredPackage(npm_package="@posthog/laudspeaker-plugin", github_repo="PostHog/posthog-plugins"),
    MonitoredPackage(npm_package="@posthog/netdata-event-processing", github_repo="PostHog/posthog-plugins"),
    MonitoredPackage(npm_package="@posthog/drop-events-on-property-plugin", github_repo="PostHog/posthog-plugins"),
    MonitoredPackage(npm_package="@posthog/filter-out-plugin", github_repo="PostHog/posthog-plugins"),
    MonitoredPackage(npm_package="@posthog/heartbeat-plugin", github_repo="PostHog/posthog-plugins"),
    MonitoredPackage(npm_package="@posthog/migrator3000-plugin", github_repo="PostHog/posthog-plugins"),
    MonitoredPackage(npm_package="@posthog/intercom-plugin", github_repo="PostHog/posthog-plugins"),
    # Other packages
    MonitoredPackage(npm_package="@posthog/piscina", github_repo="PostHog/piscina"),
    MonitoredPackage(npm_package="@posthog/clickhouse", github_repo="PostHog/clickhouse"),
    MonitoredPackage(npm_package="@posthog/siphash", github_repo="PostHog/siphash-js"),
    MonitoredPackage(npm_package="@posthog/web-dev-server", github_repo="PostHog/posthog-js"),
    MonitoredPackage(npm_package="posthog-docusaurus", github_repo="PostHog/posthog.com"),
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
