"""The workload providers whose OIDC tokens PostHog can exchange for a project token.

Trust policy validation, the token exchange and the policy settings UI read providers only from
this registry, so no provider name or issuer appears anywhere else in the backend. A provider is
supported once it has an entry in `SUPPORTED_WORKLOAD_PROVIDERS`.
"""

from __future__ import annotations

import string

from django.conf import settings
from django.db import models

from posthog.dataclasses import frozen
from posthog.workload_identity.resolvers import resolve_github_repository, resolve_gitlab_project
from posthog.workload_identity.subjects import SubjectResolver


@frozen
class WorkloadClaim:
    """A claim of the provider's OIDC token, and how the UI names it."""

    name: str
    label: str
    help_text: str = ""
    placeholder: str = ""


PRESET_VALUE = "{value}"
SNIPPET_HOST = "{host}"


@frozen
class ConditionCompanions:
    """Condition claims that match runs people don't expect on their own, so a policy that sets one of them
    must also set one of the companions."""

    claims: tuple[str, ...]
    companions: tuple[str, ...]
    # Why, in words the person who builds the policy understands.
    reason: str


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


class WorkloadProviderKey(models.TextChoices):
    GITHUB_ACTIONS = "github_actions", "GitHub Actions"
    GITLAB = "gitlab", "GitLab"
    DEPOT_CI = "depot_ci", "Depot CI"


@frozen
class WorkloadProvider:
    key: str
    name: str
    # Compared with the token's `iss` claim after trailing slashes are stripped from both.
    issuer: str
    jwks_url: str
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
    # Condition claims every policy must set, for a subject that is unique only together with them.
    required_condition_claims: tuple[str, ...] = ()
    # Condition claims that name the account, like its owner, and are the same on every run. Like the required
    # claims, they never count as the condition that limits which runs get a token.
    account_condition_claims: tuple[str, ...] = ()
    subject_lookup_conditions: tuple[tuple[str, str], ...] = ()
    # A claim that must carry the subject too, so a job running in another workload's context isn't trusted.
    subject_also_in_claim: str | None = None
    condition_companions: tuple[ConditionCompanions, ...] = ()
    # The CI config that gives a job an OIDC token, with SNIPPET_HOST where the PostHog host goes.
    setup_snippet: str = ""

    @property
    def required_presets(self) -> tuple[str, ...]:
        """Keys of the presets that set a required condition claim."""
        required = set(self.required_condition_claims)
        return tuple(
            preset.key for preset in self.condition_presets if any(claim in required for claim, _ in preset.conditions)
        )

    @property
    def default_presets(self) -> tuple[str, ...]:
        """Keys of the presets a new policy starts with: the required ones, then the first other one, so the
        policy also limits which runs get a token."""
        others = [preset.key for preset in self.condition_presets if preset.key not in self.required_presets]
        return (*self.required_presets, *others[:1])

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
        if not {*self.required_condition_claims, *self.account_condition_claims} <= set(condition_names):
            raise ValueError(f"{self.key}: required and account condition claims must be condition claims.")
        if not {claim for claim, _ in self.subject_lookup_conditions} <= set(condition_names):
            raise ValueError(f"{self.key}: subject lookup conditions must use condition claims.")
        for rule in self.condition_companions:
            if not rule.claims or not rule.companions or not {*rule.claims, *rule.companions} <= set(condition_names):
                raise ValueError(f"{self.key}: condition companions must name condition claims.")
        preset_keys = [preset.key for preset in self.condition_presets]
        if len(set(preset_keys)) != len(preset_keys):
            raise ValueError(f"{self.key}: condition presets must have unique keys.")
        for preset in self.condition_presets:
            claims = [claim for claim, _ in preset.conditions]
            if not claims or len(set(claims)) != len(claims) or not set(claims) <= set(condition_names):
                raise ValueError(f"{self.key}: preset {preset.key} must set distinct condition claims.")
            if any(value.count(PRESET_VALUE) > 1 for _, value in preset.conditions):
                raise ValueError(f"{self.key}: preset {preset.key} can use {PRESET_VALUE} once per value.")


_ACTIONS_JOB_SNIPPET = """permissions:
  id-token: write # lets hog get an OIDC token for PostHog
  contents: read
"""

GITHUB_ACTIONS = WorkloadProvider(
    key=WorkloadProviderKey.GITHUB_ACTIONS,
    name="GitHub Actions",
    issuer="https://token.actions.githubusercontent.com",
    jwks_url="https://token.actions.githubusercontent.com/.well-known/jwks",
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
    condition_companions=(
        ConditionCompanions(
            claims=("ref", "ref_protected", "workflow_ref", "job_workflow_ref", "runner_environment"),
            companions=("event_name", "environment"),
            reason="Pull request and comment runs, including ones from forks, carry the base branch's ref and workflow, so without an event or an environment the policy can trust code from outside the repository.",
        ),
    ),
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
            help_text="Jobs that deploy to this GitHub environment. Its protection rules decide who can start them. GitHub creates a missing environment without rules, so add them first.",
            conditions=(("environment", PRESET_VALUE),),
            placeholder="production",
            default_value="production",
        ),
    ),
    setup_snippet=_ACTIONS_JOB_SNIPPET,
)

GITLAB = WorkloadProvider(
    key=WorkloadProviderKey.GITLAB,
    name="GitLab",
    issuer="https://gitlab.com",
    jwks_url="https://gitlab.com/oauth/discovery/keys",
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
            name="environment_action",
            label="Environment action",
            help_text="What the job does to the environment: start deploys, while prepare, verify and access don't wait for approval.",
            placeholder="start",
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
    # project_id names a merge request's source project, so a pipeline in another project would pair it with that project's environments.
    subject_also_in_claim="job_project_id",
    condition_companions=(
        ConditionCompanions(
            claims=("ref",),
            companions=("ref_type",),
            reason="GitLab names a branch or a tag by its short name, so without the ref type a tag with a protected branch's name also matches.",
        ),
        ConditionCompanions(
            claims=("environment",),
            companions=("environment_action",),
            reason="Jobs that prepare, verify or access a protected environment don't wait for deployment approval, so without the action they also match.",
        ),
    ),
    condition_presets=(
        ConditionPreset(
            key="branch",
            label="A protected branch",
            # A fork's merge request pipeline that a maintainer runs in this project reports its source
            # branch as ref, with ref_protected false, so only the protection check keeps fork code out.
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
            conditions=(
                ("environment", PRESET_VALUE),
                ("environment_protected", "true"),
                ("environment_action", "start"),
            ),
            placeholder="production",
            default_value="production",
        ),
    ),
    setup_snippet=f"""your-job:
  id_tokens:
    HOG_ID_TOKEN: # lets hog get a PostHog token
      aud: {SNIPPET_HOST}
""",
)

DEPOT_CI = WorkloadProvider(
    key=WorkloadProviderKey.DEPOT_CI,
    name="Depot CI",
    issuer="https://identity.depot.dev",
    jwks_url="https://identity.depot.dev/keys",
    subject_claim=WorkloadClaim(
        name="repository_id",
        label="Repository ID",
        help_text="The forge's number for the repository, GitHub's for a GitHub repository. PostHog looks it up from the repository name.",
        placeholder="123456789",
    ),
    subject_name_claim=WorkloadClaim(
        name="repository",
        label="Repository",
        help_text="The owner and name, as the forge shows them.",
        placeholder="owner/repo",
    ),
    condition_claims=(
        WorkloadClaim(
            name="org_id",
            label="Depot organization ID",
            help_text="Your Depot organization ID, exactly as Depot shows it in the organization settings.",
            placeholder="abcd1234efgh",
        ),
        WorkloadClaim(
            name="forge",
            label="Forge",
            help_text="Where the repository lives. Two forges can give the same ID to different repositories.",
            placeholder="github",
        ),
        WorkloadClaim(
            name="ref",
            label="Branch or tag",
            help_text="The full ref, like refs/heads/main.",
            placeholder="refs/heads/main",
        ),
        WorkloadClaim(
            name="event_name",
            label="Event",
            help_text="What started the run, like push or workflow_dispatch.",
            placeholder="push",
        ),
        WorkloadClaim(
            name="workflow_ref",
            label="Workflow",
            help_text="The workflow file and its ref.",
            placeholder="owner/repo/ci.yaml@refs/heads/main",
        ),
        WorkloadClaim(
            name="repository_owner_id",
            label="Repository owner ID",
            help_text="The forge's number for the account that owns the repository. It survives renames.",
            placeholder="123456",
        ),
    ),
    # A repository ID is unique only within one forge, and only the organization pins the job to your Depot account.
    required_condition_claims=("org_id", "forge"),
    account_condition_claims=("repository_owner_id",),
    recorded_claims=(
        WorkloadClaim(name="repository", label="Repository"),
        WorkloadClaim(name="workflow", label="Workflow"),
        WorkloadClaim(name="run_id", label="Run"),
        WorkloadClaim(name="ref", label="Branch or tag"),
        WorkloadClaim(name="event_name", label="Event"),
    ),
    actor_label_template="{repository} · {workflow} run {run_id}",
    # Depot run IDs don't build a stable URL, and the job URL is only in the job's environment.
    run_url_template=None,
    docs_url="https://posthog.com/docs/api/workload-identity/depot",
    resolve_subject=resolve_github_repository,
    # The lookup asks GitHub, which knows nothing about another forge's repository IDs.
    subject_lookup_conditions=(("forge", "github"),),
    condition_companions=(
        ConditionCompanions(
            claims=("ref", "workflow_ref"),
            companions=("event_name",),
            reason="Pull request runs and runs started with depot ci run carry a branch's ref and workflow too, so without an event the policy can trust code nobody pushed.",
        ),
    ),
    condition_presets=(
        ConditionPreset(
            key="organization",
            label="Your Depot organization",
            help_text="Every policy pins your Depot organization and GitHub as the forge.",
            conditions=(("org_id", PRESET_VALUE), ("forge", "github")),
            placeholder="abcd1234efgh",
        ),
        ConditionPreset(
            key="branch_push",
            label="Pushes to a branch",
            help_text="Runs for commits pushed to this branch. Runs started with depot ci run have the event api, so they don't match.",
            conditions=(("ref", f"refs/heads/{PRESET_VALUE}"), ("event_name", "push")),
            placeholder="main",
            default_value="main",
        ),
    ),
    setup_snippet=_ACTIONS_JOB_SNIPPET,
)

# Can't be supported with this design:
# - Bitbucket Pipelines fixes the token's audience per workspace, so a token can't name this PostHog instance.
# - Self-managed GitLab makes each instance its own issuer, and only the issuers listed here are trusted.
# - GitHub Enterprise Cloud with a customized issuer sends https://token.actions.githubusercontent.com/<enterprise>,
#   an issuer per enterprise.
SUPPORTED_WORKLOAD_PROVIDERS: tuple[WorkloadProvider, ...] = (GITHUB_ACTIONS, GITLAB, DEPOT_CI)


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


def workload_site_url() -> str:
    """This deployment's address without a trailing slash, or empty when SITE_URL is unset. It is the `aud`
    every workload token must carry, so a token minted for another service is never accepted."""
    return (settings.SITE_URL or "").rstrip("/")
