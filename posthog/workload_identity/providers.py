"""The workload providers whose OIDC tokens PostHog can exchange for a project token.

Trust policy validation, the token exchange and the policy settings UI read providers only from
this registry, so no provider name or issuer appears anywhere else in the backend. A provider is
supported once it has an entry in `SUPPORTED_WORKLOAD_PROVIDERS`.
"""

from __future__ import annotations

import string
from enum import StrEnum

from posthog.dataclasses import frozen
from posthog.workload_identity.resolvers import resolve_github_repository, resolve_gitlab_project
from posthog.workload_identity.subjects import SubjectResolver


class AudienceCheck(StrEnum):
    # The token's `aud` must equal this deployment's SITE_URL, which the workload sets when it asks
    # its provider for the token. A token minted for another service is then never accepted.
    SITE_URL = "site_url"


@frozen
class WorkloadClaim:
    """A claim of the provider's OIDC token, and how the UI names it."""

    name: str
    label: str
    help_text: str = ""
    placeholder: str = ""


PRESET_VALUE = "{value}"
SNIPPET_HOST = "{host}"
SNIPPET_PROJECT_ID = "{project_id}"


@frozen
class ConditionPreset:
    """A common choice of conditions, so people pick "Pushes to a branch" rather than claim names."""

    key: str
    label: str
    help_text: str
    # Claim name to value. A value can hold PRESET_VALUE once, and a preset without it needs no input.
    conditions: tuple[tuple[str, str], ...]
    placeholder: str = ""
    default_value: str = ""

    @property
    def takes_value(self) -> bool:
        return any(PRESET_VALUE in value for _, value in self.conditions)


@frozen
class WorkloadProvider:
    key: str
    name: str
    # Compared with the token's `iss` claim after trailing slashes are stripped from both.
    issuer: str
    jwks_url: str
    audience_check: AudienceCheck
    # The claim every policy pins: the workload's immutable subject, for example a repository id. It
    # survives a rename, and a re-created workload gets a new one, so nobody can take over a policy by
    # claiming the old name.
    subject_claim: WorkloadClaim
    # The workload's human-readable name, for example a repository's full name. A policy pins it too,
    # so an admin approves the name they read.
    subject_name_claim: WorkloadClaim
    condition_claims: tuple[WorkloadClaim, ...]
    # The claims an activity log entry records and shows, read from the token at exchange time.
    recorded_claims: tuple[WorkloadClaim, ...]
    # How an activity log entry names the workload, formatted with the recorded claims, for example
    # "{repository} · {workflow} run {run_id}". A claim the token lacks formats as an empty string.
    actor_label_template: str
    # Formatted with the recorded claims to link an activity log entry to its run, or `None` when the
    # provider has no stable run URL.
    run_url_template: str | None
    docs_url: str
    # Looks the subject up from its name, so people don't have to find an immutable ID by hand. `None`
    # when the provider has no API PostHog can ask.
    resolve_subject: SubjectResolver | None = None
    condition_presets: tuple[ConditionPreset, ...] = ()
    # The CI config a job needs, with SNIPPET_HOST and SNIPPET_PROJECT_ID where the values go.
    setup_snippet: str = ""

    def setup_snippet_for(self, *, host: str, project_id: int) -> str:
        return self.setup_snippet.replace(SNIPPET_HOST, host).replace(SNIPPET_PROJECT_ID, str(project_id))

    def __post_init__(self) -> None:
        condition_names = [claim.name for claim in self.condition_claims]
        if len(set(condition_names)) != len(condition_names):
            raise ValueError(f"{self.key}: condition claims must be unique.")
        if {self.subject_claim.name, self.subject_name_claim.name} & set(condition_names):
            raise ValueError(f"{self.key}: the subject claims can't also be condition claims.")
        # The activity log fills the templates with the recorded claims only, so a field outside them, or a
        # positional, attribute or index field, would fail or render empty on the first workload write.
        recorded_names = {claim.name for claim in self.recorded_claims}
        for template in (self.actor_label_template, self.run_url_template or ""):
            fields = [name for _, name, _, _ in string.Formatter().parse(template) if name is not None]
            unknown = sorted(set(fields) - recorded_names)
            if unknown:
                raise ValueError(f"{self.key}: templates can only use recorded claims, not {unknown}.")
        preset_keys = [preset.key for preset in self.condition_presets]
        if len(set(preset_keys)) != len(preset_keys):
            raise ValueError(f"{self.key}: condition presets must have unique keys.")
        for preset in self.condition_presets:
            claims = [claim for claim, _ in preset.conditions]
            if not claims or len(set(claims)) != len(claims) or not set(claims) <= set(condition_names):
                raise ValueError(f"{self.key}: preset {preset.key} must set distinct condition claims.")
            if any(value.count(PRESET_VALUE) > 1 for _, value in preset.conditions):
                raise ValueError(f"{self.key}: preset {preset.key} can use {PRESET_VALUE} once per value.")


GITHUB_ACTIONS = WorkloadProvider(
    key="github_actions",
    name="GitHub Actions",
    issuer="https://token.actions.githubusercontent.com",
    jwks_url="https://token.actions.githubusercontent.com/.well-known/jwks",
    audience_check=AudienceCheck.SITE_URL,
    subject_claim=WorkloadClaim(
        name="repository_id",
        label="Repository ID",
        help_text="GitHub's number for the repository. PostHog looks it up from the repository name.",
        placeholder="123456789",
    ),
    subject_name_claim=WorkloadClaim(
        name="repository",
        label="Repository",
        help_text="The owner and name, as GitHub shows them.",
        placeholder="owner/repo",
    ),
    condition_claims=(
        WorkloadClaim(
            name="ref",
            label="Branch or tag",
            help_text="The full ref, like refs/heads/main or refs/tags/v1.0.0.",
            placeholder="refs/heads/main",
        ),
        WorkloadClaim(
            name="environment",
            label="Environment",
            help_text="The GitHub environment the job deploys to.",
            placeholder="production",
        ),
        WorkloadClaim(
            name="ref_protected",
            label="Protected ref",
            help_text="true when any branch protection or ruleset covers the ref, whatever its rules are.",
            placeholder="true",
        ),
        WorkloadClaim(
            name="event_name",
            label="Event",
            help_text="What started the run, like push, workflow_dispatch or schedule.",
            placeholder="push",
        ),
        WorkloadClaim(
            name="workflow_ref",
            label="Workflow",
            help_text="The workflow file and its ref.",
            placeholder="owner/repo/.github/workflows/deploy.yml@refs/heads/main",
        ),
        WorkloadClaim(
            name="job_workflow_ref",
            label="Reusable workflow",
            help_text="For a job that calls a reusable workflow, that workflow's file and ref.",
            placeholder="owner/shared/.github/workflows/release.yml@refs/heads/main",
        ),
        WorkloadClaim(
            name="runner_environment",
            label="Runner",
            help_text="github-hosted or self-hosted.",
            placeholder="github-hosted",
        ),
    ),
    recorded_claims=(
        WorkloadClaim(name="repository", label="Repository"),
        WorkloadClaim(name="workflow", label="Workflow"),
        WorkloadClaim(name="run_id", label="Run"),
        WorkloadClaim(name="run_attempt", label="Attempt"),
        WorkloadClaim(name="sha", label="Commit"),
        WorkloadClaim(name="ref", label="Branch or tag"),
        WorkloadClaim(name="environment", label="Environment"),
        WorkloadClaim(name="event_name", label="Event"),
        WorkloadClaim(name="actor", label="Started by"),
    ),
    actor_label_template="{repository} · {workflow} run {run_id}",
    run_url_template="https://github.com/{repository}/actions/runs/{run_id}",
    docs_url="https://posthog.com/docs/api/workload-identity/github-actions",
    resolve_subject=resolve_github_repository,
    condition_presets=(
        ConditionPreset(
            key="branch_push",
            label="Pushes to a branch",
            # A pull_request_target run from a fork carries the base branch as its ref, so the event pins
            # the preset to code that is on the branch.
            help_text="Runs for commits pushed to this branch. Pull request runs don't match, even ones that target the branch.",
            conditions=(("ref", f"refs/heads/{PRESET_VALUE}"), ("event_name", "push")),
            placeholder="main",
            default_value="main",
        ),
        ConditionPreset(
            key="environment",
            label="A deployment environment",
            help_text="Jobs that deploy to this GitHub environment. Its protection rules decide who can start them.",
            conditions=(("environment", PRESET_VALUE),),
            placeholder="production",
            default_value="production",
        ),
    ),
    setup_snippet=f"""permissions:
  id-token: write # lets hog get an OIDC token for PostHog
  contents: read
env:
  HOG_HOST: {SNIPPET_HOST}
  HOG_PROJECT_ID: "{SNIPPET_PROJECT_ID}"
""",
)

GITLAB = WorkloadProvider(
    key="gitlab",
    name="GitLab",
    issuer="https://gitlab.com",
    jwks_url="https://gitlab.com/oauth/discovery/keys",
    audience_check=AudienceCheck.SITE_URL,
    subject_claim=WorkloadClaim(
        name="project_id",
        label="Project ID",
        help_text="GitLab's number for the project. PostHog looks it up from the project path.",
        placeholder="12345678",
    ),
    subject_name_claim=WorkloadClaim(
        name="project_path",
        label="Project path",
        help_text="The full path, as GitLab shows it, with any subgroups.",
        placeholder="group/project",
    ),
    condition_claims=(
        WorkloadClaim(
            name="ref",
            label="Branch or tag",
            help_text="The short name, like main or v1.0.0.",
            placeholder="main",
        ),
        WorkloadClaim(name="ref_type", label="Ref type", help_text="branch or tag.", placeholder="branch"),
        WorkloadClaim(
            name="ref_protected",
            label="Protected ref",
            help_text="true when the branch or tag is protected.",
            placeholder="true",
        ),
        WorkloadClaim(
            name="environment",
            label="Environment",
            help_text="The environment the job deploys to.",
            placeholder="production",
        ),
        WorkloadClaim(
            name="environment_protected",
            label="Protected environment",
            help_text="true when the environment is protected.",
            placeholder="true",
        ),
        WorkloadClaim(
            name="pipeline_source",
            label="Pipeline source",
            help_text="What started the pipeline, like push, schedule or web.",
            placeholder="push",
        ),
        WorkloadClaim(
            name="ci_config_ref_uri",
            label="Pipeline config",
            help_text="The config file and its ref.",
            placeholder="gitlab.com/group/project//.gitlab-ci.yml@refs/heads/main",
        ),
    ),
    recorded_claims=(
        WorkloadClaim(name="project_path", label="Project"),
        WorkloadClaim(name="job_project_path", label="Pipeline project"),
        WorkloadClaim(name="pipeline_id", label="Pipeline"),
        WorkloadClaim(name="job_id", label="Job"),
        WorkloadClaim(name="sha", label="Commit"),
        WorkloadClaim(name="ref", label="Branch or tag"),
        WorkloadClaim(name="environment", label="Environment"),
        WorkloadClaim(name="pipeline_source", label="Pipeline source"),
        WorkloadClaim(name="user_login", label="Started by"),
    ),
    actor_label_template="{project_path} · pipeline {pipeline_id}",
    # A merge request pipeline from a fork can run in the parent project, which job_project_path names.
    run_url_template="https://gitlab.com/{job_project_path}/-/jobs/{job_id}",
    docs_url="https://posthog.com/docs/api/workload-identity/gitlab",
    resolve_subject=resolve_gitlab_project,
    condition_presets=(
        ConditionPreset(
            key="branch",
            label="A protected branch",
            # A merge request pipeline from a fork carries the fork's project_id, so the branch alone can't
            # trust code from a fork. Protection keeps working if someone later reuses the branch name.
            help_text="Pipelines that run on this branch while it is protected.",
            conditions=(("ref", PRESET_VALUE), ("ref_type", "branch"), ("ref_protected", "true")),
            placeholder="main",
            default_value="main",
        ),
        ConditionPreset(
            key="environment",
            label="A protected environment",
            # Anyone who can push a branch can name any unprotected environment in a job.
            help_text="Jobs that deploy to this environment while it is protected. Protected environments need GitLab Premium or Ultimate.",
            conditions=(("environment", PRESET_VALUE), ("environment_protected", "true")),
            placeholder="production",
            default_value="production",
        ),
    ),
    setup_snippet=f"""your-job:
  id_tokens:
    HOG_ID_TOKEN: # lets hog get a PostHog token
      aud: {SNIPPET_HOST}
  variables:
    HOG_HOST: {SNIPPET_HOST}
    HOG_PROJECT_ID: "{SNIPPET_PROJECT_ID}"
""",
)

# Can't be supported with this design:
# - Bitbucket Pipelines fixes the token's audience per workspace, so a token can't name this PostHog instance.
# - Self-managed GitLab makes each instance its own issuer, and only the issuers listed here are trusted.
# - GitHub Enterprise Cloud with a customized issuer sends https://token.actions.githubusercontent.com/<enterprise>,
#   an issuer per enterprise.
SUPPORTED_WORKLOAD_PROVIDERS: tuple[WorkloadProvider, ...] = (GITHUB_ACTIONS, GITLAB)


def normalize_issuer(issuer: str) -> str:
    return issuer.rstrip("/")


def get_supported_workload_providers() -> tuple[WorkloadProvider, ...]:
    return SUPPORTED_WORKLOAD_PROVIDERS


def get_workload_provider_by_issuer(issuer: str) -> WorkloadProvider | None:
    normalized = normalize_issuer(issuer)
    if not normalized:
        return None
    for provider in get_supported_workload_providers():
        if normalize_issuer(provider.issuer) == normalized:
            return provider
    return None


def get_workload_provider_by_key(key: str) -> WorkloadProvider | None:
    for provider in get_supported_workload_providers():
        if provider.key == key:
            return provider
    return None
