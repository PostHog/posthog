import dataclasses
from datetime import datetime

from django.conf import settings

import aiohttp
import structlog
from temporalio import activity

logger = structlog.get_logger(__name__)


@dataclasses.dataclass
class NpmVersionInfo:
    package: str
    version: str
    published_at: datetime


@dataclasses.dataclass
class GitHubWorkflowRun:
    repo: str
    workflow_name: str
    conclusion: str
    created_at: datetime
    html_url: str


@dataclasses.dataclass
class UnauthorizedRelease:
    package: str
    version: str
    published_at: datetime
    github_repo: str
    reason: str


@dataclasses.dataclass
class FetchNpmVersionsInput:
    packages: list[str]
    since_timestamp: str | None = None


@dataclasses.dataclass
class FetchNpmVersionsOutput:
    versions: list[dict]
    errors: list[str]


@activity.defn(name="npm-release-monitor-fetch-npm-versions")
async def fetch_npm_versions(input: FetchNpmVersionsInput) -> FetchNpmVersionsOutput:
    """Fetch recent versions from npm registry for the given packages."""
    versions: list[dict] = []
    errors: list[str] = []

    since = None
    if input.since_timestamp:
        since = datetime.fromisoformat(input.since_timestamp.replace("Z", "+00:00"))

    async with aiohttp.ClientSession() as session:
        for package in input.packages:
            try:
                url = f"https://registry.npmjs.org/{package}"
                async with session.get(url) as response:
                    if response.status == 404:
                        logger.warning("npm package not found", package=package)
                        continue
                    if response.status != 200:
                        errors.append(f"Failed to fetch {package}: HTTP {response.status}")
                        continue

                    data = await response.json()
                    time_data = data.get("time", {})

                    for version, timestamp_str in time_data.items():
                        if version in ("created", "modified"):
                            continue

                        try:
                            published_at = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                        except ValueError:
                            continue

                        if since and published_at <= since:
                            continue

                        versions.append(
                            {
                                "package": package,
                                "version": version,
                                "published_at": published_at.isoformat(),
                            }
                        )

            except Exception as e:
                errors.append(f"Error fetching {package}: {e!s}")
                logger.exception("Error fetching npm package", package=package, error=str(e))

    return FetchNpmVersionsOutput(versions=versions, errors=errors)


@dataclasses.dataclass
class FetchGitHubWorkflowRunsInput:
    repos: list[str]
    since_timestamp: str
    github_token: str | None = None


@dataclasses.dataclass
class FetchGitHubWorkflowRunsOutput:
    runs: list[dict]
    errors: list[str]


@activity.defn(name="npm-release-monitor-fetch-github-runs")
async def fetch_github_workflow_runs(input: FetchGitHubWorkflowRunsInput) -> FetchGitHubWorkflowRunsOutput:
    """Fetch workflow runs from GitHub for the given repos."""
    runs: list[dict] = []
    errors: list[str] = []

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "PostHog-NPM-Release-Monitor",
    }

    github_token = input.github_token or getattr(settings, "GITHUB_TOKEN", None)
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    async with aiohttp.ClientSession() as session:
        for repo in input.repos:
            try:
                url = f"https://api.github.com/repos/{repo}/actions/runs"
                params = {"created": f">={input.since_timestamp}", "per_page": 100}

                async with session.get(url, headers=headers, params=params) as response:
                    if response.status == 404:
                        logger.warning("GitHub repo not found or no access", repo=repo)
                        continue
                    if response.status == 403:
                        errors.append(f"Rate limited or forbidden for {repo}")
                        continue
                    if response.status != 200:
                        errors.append(f"Failed to fetch runs for {repo}: HTTP {response.status}")
                        continue

                    data = await response.json()
                    workflow_runs = data.get("workflow_runs", [])

                    for run in workflow_runs:
                        runs.append(
                            {
                                "repo": repo,
                                "workflow_name": run.get("name", ""),
                                "conclusion": run.get("conclusion", ""),
                                "created_at": run.get("created_at", ""),
                                "html_url": run.get("html_url", ""),
                            }
                        )

            except Exception as e:
                errors.append(f"Error fetching runs for {repo}: {e!s}")
                logger.exception("Error fetching GitHub workflow runs", repo=repo, error=str(e))

    return FetchGitHubWorkflowRunsOutput(runs=runs, errors=errors)


@dataclasses.dataclass
class CorrelateReleasesInput:
    npm_versions: list[dict]
    github_runs: list[dict]
    packages_config: list[dict]


@dataclasses.dataclass
class CorrelateReleasesOutput:
    unauthorized_releases: list[dict]
    correlated_releases: list[dict]


@activity.defn(name="npm-release-monitor-correlate-releases")
async def correlate_releases(input: CorrelateReleasesInput) -> CorrelateReleasesOutput:
    """Check if npm releases correlate with GitHub CI/CD runs."""
    unauthorized: list[dict] = []
    correlated: list[dict] = []

    packages_by_name = {p["npm_package"]: p for p in input.packages_config}

    github_runs_by_repo: dict[str, list[dict]] = {}
    for run in input.github_runs:
        repo = run["repo"]
        if repo not in github_runs_by_repo:
            github_runs_by_repo[repo] = []
        github_runs_by_repo[repo].append(run)

    for npm_version in input.npm_versions:
        package_name = npm_version["package"]
        config = packages_by_name.get(package_name)

        if not config:
            logger.warning("No config found for package", package=package_name)
            continue

        github_repo = config["github_repo"]
        workflow_names = config.get("workflow_names", ["Release", "Publish", "release", "publish"])
        time_window = config.get("time_window_minutes", 10)

        published_at = datetime.fromisoformat(npm_version["published_at"].replace("Z", "+00:00"))
        repo_runs = github_runs_by_repo.get(github_repo, [])

        found_correlation = False
        for run in repo_runs:
            if run["conclusion"] != "success":
                continue

            run_name = run["workflow_name"]
            if not any(wn.lower() in run_name.lower() for wn in workflow_names):
                continue

            run_time = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
            time_diff = abs((published_at - run_time).total_seconds()) / 60

            if time_diff <= time_window:
                found_correlation = True
                correlated.append(
                    {
                        "package": package_name,
                        "version": npm_version["version"],
                        "published_at": npm_version["published_at"],
                        "workflow_url": run["html_url"],
                    }
                )
                break

        if not found_correlation:
            unauthorized.append(
                {
                    "package": package_name,
                    "version": npm_version["version"],
                    "published_at": npm_version["published_at"],
                    "github_repo": github_repo,
                    "reason": f"No matching CI/CD workflow run found within {time_window} minutes of publish",
                }
            )
            logger.warning(
                "Unauthorized release detected",
                package=package_name,
                version=npm_version["version"],
                published_at=npm_version["published_at"],
                github_repo=github_repo,
            )

    return CorrelateReleasesOutput(unauthorized_releases=unauthorized, correlated_releases=correlated)


@dataclasses.dataclass
class SendAlertsInput:
    unauthorized_releases: list[dict]
    alert_email: str | None = None
    slack_webhook_url: str | None = None


@dataclasses.dataclass
class SendAlertsOutput:
    alerts_sent: int
    errors: list[str]


@activity.defn(name="npm-release-monitor-send-alerts")
async def send_alerts(input: SendAlertsInput) -> SendAlertsOutput:
    """Send alerts for unauthorized releases."""
    from posthog.cdp.internal_events import InternalEventEvent, produce_internal_event
    from posthog.email import EmailMessage

    alerts_sent = 0
    errors: list[str] = []

    if not input.unauthorized_releases:
        return SendAlertsOutput(alerts_sent=0, errors=[])

    for release in input.unauthorized_releases:
        logger.critical(
            "SECURITY ALERT: Unauthorized npm release detected",
            package=release["package"],
            version=release["version"],
            published_at=release["published_at"],
            github_repo=release["github_repo"],
            reason=release["reason"],
        )

        try:
            produce_internal_event(
                team_id=1,
                event=InternalEventEvent(
                    event="$npm_unauthorized_release_detected",
                    distinct_id="npm-release-monitor",
                    properties={
                        "package": release["package"],
                        "version": release["version"],
                        "published_at": release["published_at"],
                        "github_repo": release["github_repo"],
                        "reason": release["reason"],
                        "severity": "critical",
                    },
                ),
            )
            alerts_sent += 1
        except Exception as e:
            errors.append(f"Failed to produce internal event: {e!s}")
            logger.exception("Failed to send alert", error=str(e))

    if input.slack_webhook_url:
        async with aiohttp.ClientSession() as session:
            for release in input.unauthorized_releases:
                try:
                    payload = {
                        "text": f":rotating_light: *SECURITY ALERT: Unauthorized npm release detected*",
                        "blocks": [
                            {
                                "type": "header",
                                "text": {
                                    "type": "plain_text",
                                    "text": ":rotating_light: Unauthorized npm Release Detected",
                                },
                            },
                            {
                                "type": "section",
                                "fields": [
                                    {"type": "mrkdwn", "text": f"*Package:*\n`{release['package']}`"},
                                    {"type": "mrkdwn", "text": f"*Version:*\n`{release['version']}`"},
                                    {"type": "mrkdwn", "text": f"*Published:*\n{release['published_at']}"},
                                    {"type": "mrkdwn", "text": f"*Expected Repo:*\n{release['github_repo']}"},
                                ],
                            },
                            {
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": f"*Reason:*\n{release['reason']}",
                                },
                            },
                            {
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": f"<https://www.npmjs.com/package/{release['package']}|View on npm>",
                                },
                            },
                        ],
                    }
                    async with session.post(input.slack_webhook_url, json=payload) as response:
                        if response.status != 200:
                            errors.append(f"Slack webhook failed: HTTP {response.status}")
                except Exception as e:
                    errors.append(f"Slack webhook error: {e!s}")

    if input.alert_email:
        try:
            for release in input.unauthorized_releases:
                message = EmailMessage(
                    campaign_key=f"npm-unauthorized-release-{release['package']}-{release['version']}",
                    subject=f"SECURITY ALERT: Unauthorized npm release - {release['package']}@{release['version']}",
                    template_name="npm_unauthorized_release_alert",
                    template_context={
                        "package": release["package"],
                        "version": release["version"],
                        "published_at": release["published_at"],
                        "github_repo": release["github_repo"],
                        "reason": release["reason"],
                        "npm_url": f"https://www.npmjs.com/package/{release['package']}",
                    },
                )
                message.add_recipient(email=input.alert_email)
                message.send()
                alerts_sent += 1
        except Exception as e:
            errors.append(f"Email alert error: {e!s}")

    return SendAlertsOutput(alerts_sent=alerts_sent, errors=errors)
