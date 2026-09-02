from enum import StrEnum

__all__ = ["RunMode", "derive_run_mode", "run_mode"]


class RunMode(StrEnum):
    """How this PostHog process is deployed."""

    CLOUD_US = "US"
    CLOUD_EU = "EU"
    CLOUD_DEV = "DEV"
    E2E = "E2E"
    LOCAL = "LOCAL"
    HOBBY = "HOBBY"

    @property
    def is_prod_cloud(self) -> bool:
        """Customer-facing PostHog Cloud: US or EU, excluding staging."""
        return self is RunMode.CLOUD_US or self is RunMode.CLOUD_EU

    @property
    def is_deployed_cloud(self) -> bool:
        """A cloud environment backed by deployed infrastructure: US, EU, or staging.

        Excludes E2E, which runs against a local single-node stack. This is the
        distinction ClickHouse migrations gate on.
        """
        return self.is_prod_cloud or self is RunMode.CLOUD_DEV

    @property
    def is_cloud(self) -> bool:
        """Any cloud mode, E2E included. Matches `posthog.cloud_utils.is_cloud`."""
        return self.is_deployed_cloud or self is RunMode.E2E

    @property
    def is_hobby(self) -> bool:
        """Self-hosted: no cloud deployment and not local dev."""
        return self is RunMode.HOBBY

    @property
    def region(self) -> str | None:
        """`US`, `EU` or `DEV` on a deployed cloud env, else None."""
        return self.value if self.is_deployed_cloud else None


def derive_run_mode(cloud_deployment: str | None, debug: bool) -> RunMode:
    """Resolve a run mode from the two settings that define it.

    An unrecognized `cloud_deployment` resolves to LOCAL or HOBBY rather than raising,
    so a typo'd value silently disables every cloud-gated code path instead of failing
    the process.
    """
    match (cloud_deployment or "").upper():
        case "US":
            return RunMode.CLOUD_US
        case "EU":
            return RunMode.CLOUD_EU
        case "DEV":
            return RunMode.CLOUD_DEV
        case "E2E":
            return RunMode.E2E
        case "LOCAL":
            return RunMode.LOCAL
        case _:
            return RunMode.LOCAL if debug else RunMode.HOBBY


def run_mode() -> RunMode:
    """The current run mode, read from `posthog.settings` on every call.

    Deliberately not cached: ClickHouse migrations resolve their `operations` at
    module scope, and their tests re-import those modules under a patched
    `posthog.settings.CLOUD_DEPLOYMENT` to check each deployment's branch.
    """
    # Module-level import would cycle: posthog.settings -> posthog.settings.utils ->
    # posthog.utils -> posthog.cloud_utils, and cloud_utils imports this module.
    from posthog import settings  # noqa: PLC0415

    return derive_run_mode(settings.CLOUD_DEPLOYMENT, settings.DEBUG)
