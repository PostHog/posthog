import shutil
import textwrap
from pathlib import Path
from typing import Any

import pytest

from django.test import SimpleTestCase

import mypy.api
from hogli_commands.projections import PROJECTIONS, OutputFormatter, ProjectionRunner
from parameterized import parameterized

from posthog.integrations import IntegrationManager
from posthog.integrations.accessors import AuthAccessor, IntegrationReader, OAuthAccessor
from posthog.integrations.catalogue import KINDS
from posthog.integrations.contracts import UnsupportedIntegrationFilter
from posthog.integrations.enums import AuthType
from posthog.integrations.kinds_generated import IntegrationKind
from posthog.models.integration import Integration

REPO_ROOT = Path(__file__).resolve().parents[3]
SDK_DIR = REPO_ROOT / "posthog/integrations"


# The default auth type of a kind is stored data: a row without `config["auth_type"]` has it.
# A change here needs a data migration for the rows of the kind, and a deliberate edit of this mapping.
FROZEN_KIND_DEFAULTS: dict[str, str] = {
    "anthropic": "token",
    "apns": "credentials",
    "apple-ads": "oauth",
    "aws-redshift": "credentials",
    "aws-s3": "credentials",
    "azure-blob": "credentials",
    "bing-ads": "oauth",
    "clickup": "oauth",
    "customerio-app": "token",
    "customerio-track": "token",
    "customerio-webhook": "token",
    "databricks": "credentials",
    "email": "credentials",
    "firebase": "credentials",
    "github": "oauth",
    "gitlab": "token",
    "google-ads": "oauth",
    "google-analytics": "oauth",
    "google-calendar": "oauth",
    "google-cloud-service-account": "credentials",
    "google-cloud-storage": "credentials",
    "google-pubsub": "credentials",
    "google-search-console": "oauth",
    "google-sheets": "oauth",
    "helpscout": "oauth",
    "hubspot": "oauth",
    "instagram": "oauth",
    "intercom": "oauth",
    "jira": "oauth",
    "linear": "oauth",
    "linkedin-ads": "oauth",
    "meta-ads": "oauth",
    "pardot": "oauth",
    "pinterest-ads": "oauth",
    "postgresql": "credentials",
    "posthog": "oauth",
    "reddit-ads": "oauth",
    "resend": "oauth",
    "s3-compatible": "credentials",
    "salesforce": "oauth",
    "slack": "oauth",
    "slack-posthog-code": "oauth",
    "snapchat": "oauth",
    "snowflake": "credentials",
    "stripe": "oauth",
    "tiktok-ads": "oauth",
    "twilio": "token",
    "twitter-ads": "oauth",
    "vercel": "oauth",
    "youtube-analytics": "oauth",
}


class TestCatalogue(SimpleTestCase):
    def test_kinds_match_the_model_choices(self) -> None:
        assert set(KINDS) == set(Integration.IntegrationKind.values) == {kind.value for kind in IntegrationKind}

    def test_kind_defaults_do_not_change(self) -> None:
        assert {kind: spec.default.value for kind, spec in KINDS.items()} == FROZEN_KIND_DEFAULTS

    def test_generated_file_is_in_sync_with_the_catalogue(self) -> None:
        [projection] = [projection for projection in PROJECTIONS if projection.name == "integration-kinds"]
        runner = ProjectionRunner(REPO_ROOT, [projection], OutputFormatter(REPO_ROOT))

        assert runner.stale(projection) == [], "Run `hogli build:projections --only integration-kinds`."

    @parameterized.expand([(kind,) for kind in sorted(KINDS)])
    def test_each_kind_has_exactly_its_supported_auth_types(self, kind: str) -> None:
        accessor = getattr(IntegrationManager, kind.replace("-", "_"))
        present = {auth_type for auth_type in AuthType if hasattr(accessor, auth_type.value)}

        assert present == KINDS[kind].supported
        expected = {AuthType.OAUTH: OAuthAccessor, AuthType.TOKEN: AuthAccessor, AuthType.CREDENTIALS: AuthAccessor}
        assert all(type(getattr(accessor, auth_type.value)) is expected[auth_type] for auth_type in present)
        assert type(accessor.any) is IntegrationReader

    @parameterized.expand(
        [
            ("create",),
            ("upsert",),
            ("update",),
            ("refresh_access_token",),
            ("update_by_external_id",),
            ("acreate",),
            ("aupdate",),
        ]
    )
    def test_any_readers_have_no_writes(self, method: str) -> None:
        assert not hasattr(IntegrationManager.any, method)
        assert not hasattr(IntegrationManager.stripe.any, method)
        assert hasattr(IntegrationManager.stripe.oauth, method)

    @parameterized.expand(
        [
            ("lookup_in_key", {"account__name": "a"}),
            ("auth_type_key", {"auth_type": "token"}),
            ("marker_key", {"warehouse_source_type": "Stripe"}),
            ("empty_key", {"": "a"}),
            ("key_with_a_dash", {"a-b": "a"}),
            ("key_starts_with_a_digit", {"1a": "a"}),
            ("dict_value", {"account": {"name": "a"}}),
            ("list_value", {"ids": [1, 2]}),
            ("tuple_value", {"ids": (1,)}),
        ]
    )
    def test_find_rejects_unsupported_filters(self, _name: str, where: dict[str, Any]) -> None:
        with self.assertRaises(UnsupportedIntegrationFilter):
            IntegrationManager.github.oauth.find(1, where=where)


# The SDK modules are copied into an empty directory, so mypy reads them without the Django plugin
# and without following imports into the rest of the repo. Imports it cannot find become `Any`.
SDK_FILES = (
    "__init__.py",
    "accessors.py",
    "catalogue.py",
    "contracts.py",
    "enums.py",
    "kinds_generated.py",
    "manager.py",
    "observability.py",
    "source_kinds.py",
    "usages.py",
)

SNIPPET = """
from posthog.integrations import IntegrationManager

IntegrationManager.github.oauth.create(1, external_id="x", config={})
IntegrationManager.github.token.upsert(1, "x", config={})
IntegrationManager.source("ably").token.create(1, external_id="x", config={})
IntegrationManager.stripe.any.get(1, 2)
IntegrationManager.any.list(1)
IntegrationManager.stripe.any.create(1, external_id="x", config={})
IntegrationManager.github.credentials
IntegrationManager.any.update(1, 2, errors="")
IntegrationManager.postgresql.oauth
IntegrationManager.stripe.any.upsert(1, "x", config={})
row = IntegrationManager.github.oauth.get(1, 2)
row.save()
row.delete()
row.config["x"] = 1
row.objects
IntegrationManager.github.token.refresh_access_token(1, 2)
row.config.get("x")
IntegrationManager.resend.oauth.refresh_access_token(1, 2, stale_access_token="t").sensitive_config
"""


@pytest.mark.timeout(300)
def test_mypy_rejects_unsupported_auth_types_writes_through_any_and_row_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # mypy also searches the working directory, which would pull in the whole repo.
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "src"
    for relative in SDK_FILES:
        target = root / "posthog/integrations" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(SDK_DIR / relative, target)
    (root / "posthog/__init__.py").touch()
    (root / "snippet.py").write_text(textwrap.dedent(SNIPPET))
    (tmp_path / "mypy.ini").write_text("[mypy]\n")

    stdout, stderr, _ = mypy.api.run(
        [
            "--config-file",
            str(tmp_path / "mypy.ini"),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--no-site-packages",
            "--ignore-missing-imports",
            "--no-error-summary",
            "--hide-error-context",
            str(root / "snippet.py"),
        ]
    )

    errors = sorted(
        (int(line.split(":")[1]), line.split(": error: ")[1].split("  [")[0])
        for line in stdout.splitlines()
        if "snippet.py" in line and ": error: " in line
    )
    assert errors == [
        (9, '"IntegrationReader" has no attribute "create"'),
        (10, '"GithubKind" has no attribute "credentials"'),
        (11, '"IntegrationReader" has no attribute "update"'),
        (12, '"PostgresqlKind" has no attribute "oauth"'),
        (13, '"IntegrationReader" has no attribute "upsert"'),
        (15, '"IntegrationRecord" has no attribute "save"'),
        (16, '"IntegrationRecord" has no attribute "delete"'),
        (17, 'Unsupported target for indexed assignment ("Mapping[str, Any]")'),
        (18, '"IntegrationRecord" has no attribute "objects"'),
        (19, '"AuthAccessor" has no attribute "refresh_access_token"'),
    ], stdout + stderr
