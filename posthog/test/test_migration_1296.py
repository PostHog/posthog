from datetime import timedelta
from typing import Any

from posthog.test.base import TestMigrations

from django.utils import timezone

from parameterized import parameterized


class BackfillCimdVerificationTokenUrlMigrationTest(TestMigrations):
    migrate_from = "1295_cimdverificationtoken_cimd_url"
    migrate_to = "1296_backfill_cimd_verification_token_url"

    CLASS_DATA_LEVEL_SETUP = False

    def setUpBeforeMigration(self, apps: Any) -> None:
        Organization = apps.get_model("posthog", "Organization")
        OAuthApplication = apps.get_model("posthog", "OAuthApplication")
        CIMDVerificationToken = apps.get_model("posthog", "CIMDVerificationToken")
        self.CIMDVerificationToken = CIMDVerificationToken

        base_time = timezone.now() - timedelta(days=30)

        # The historical model skips Organization.save's slug generation, so every org would
        # otherwise collide on the unique empty slug.
        def make_org(slug: str) -> Any:
            return Organization.objects.create(name=f"Org {slug}", slug=slug)

        def make_app(slug: str, org: Any, url: str, created: Any = base_time) -> Any:
            app = OAuthApplication.objects.create(
                name=f"App {slug}",
                client_id=f"client-{slug}",
                client_secret="",
                client_type="confidential",
                authorization_grant_type="authorization-code",
                redirect_uris="https://example.com/callback",
                algorithm="RS256",
                organization=org,
                is_cimd_client=True,
                cimd_metadata_url=url,
            )
            # `created` is auto_now_add, so the value passed to create() above is
            # discarded on INSERT; .update() bypasses pre_save and lands it for real.
            OAuthApplication.objects.filter(pk=app.pk).update(created=created)
            return app

        def make_token(
            slug: str,
            org: Any,
            created_at: Any = base_time - timedelta(days=1),
            last_used_at: Any = base_time,
            cimd_url: str | None = None,
        ) -> Any:
            return CIMDVerificationToken.objects.create(
                organization=org,
                label=slug,
                secure_value=f"secure-{slug}",
                mask_value="x" * 11,
                created_at=created_at,
                last_used_at=last_used_at,
                cimd_url=cimd_url,
            )

        self.tokens: dict[str, Any] = {}

        # Unambiguous: one verified app, one corroborated token.
        org_happy = make_org("happy")
        make_app("happy", org_happy, "https://happy.example.com/.well-known/oauth-client-metadata.json")
        self.tokens["happy"] = make_token("happy", org_happy)

        # Two tokens on the org: can't tell which one verified the app.
        org_two_tokens = make_org("two-tokens")
        make_app("two-tokens", org_two_tokens, "https://two-tokens.example.com/.well-known/oauth-client-metadata.json")
        self.tokens["two_tokens_1"] = make_token("two-tokens-1", org_two_tokens)
        self.tokens["two_tokens_2"] = make_token("two-tokens-2", org_two_tokens)

        # Two apps at different URLs: ambiguous which one the token belongs to.
        org_diff_urls = make_org("diff-urls")
        make_app("diff-urls-1", org_diff_urls, "https://diff-urls-1.example.com/.well-known/oauth-client-metadata.json")
        make_app("diff-urls-2", org_diff_urls, "https://diff-urls-2.example.com/.well-known/oauth-client-metadata.json")
        self.tokens["diff_urls"] = make_token("diff-urls", org_diff_urls)

        # Two apps whose URLs differ only in spelling: cimd_metadata_url is unique, so this
        # is the only way two rows can name one document. They agree, so it is not ambiguous.
        org_same_url = make_org("same-url")
        make_app("same-url-1", org_same_url, "https://same-url.example.com/.well-known/oauth-client-metadata.json")
        make_app("same-url-2", org_same_url, "https://SAME-URL.example.com:443/.well-known/oauth-client-metadata.json")
        self.tokens["same_url"] = make_token("same-url", org_same_url)

        # Token never verified anything: no claim to any URL.
        org_never_used = make_org("never-used")
        make_app("never-used", org_never_used, "https://never-used.example.com/.well-known/oauth-client-metadata.json")
        self.tokens["never_used"] = make_token("never-used", org_never_used, last_used_at=None)

        # Token issued after the app self-registered, which is the ordinary sequence and
        # must still backfill.
        org_created_after = make_org("created-after")
        make_app(
            "created-after",
            org_created_after,
            "https://created-after.example.com/.well-known/oauth-client-metadata.json",
        )
        self.tokens["created_after_app"] = make_token(
            "created-after",
            org_created_after,
            created_at=base_time + timedelta(days=1),
            last_used_at=base_time + timedelta(days=2),
        )

        # Token already carries a deliberately-set cimd_url: replay must not clobber it.
        org_already_bound = make_org("already-bound")
        make_app(
            "already-bound",
            org_already_bound,
            "https://already-bound-app.example.com/.well-known/oauth-client-metadata.json",
        )
        self.tokens["already_bound"] = make_token(
            "already-bound", org_already_bound, cimd_url="https://already-bound.example.com/manual"
        )

        # App URL carries an explicit :443 that normalization must strip.
        org_port = make_org("port-443")
        make_app("port-443", org_port, "https://port-443.example.com:443/.well-known/oauth-client-metadata.json")
        self.tokens["port_443"] = make_token("port-443", org_port)

        # App URL carries a trailing slash that normalization must strip.
        org_slash = make_org("trailing-slash")
        make_app(
            "trailing-slash", org_slash, "https://trailing-slash.example.com/.well-known/oauth-client-metadata.json/"
        )
        self.tokens["trailing_slash"] = make_token("trailing-slash", org_slash)

    @parameterized.expand(
        [
            ("happy", "https://happy.example.com/.well-known/oauth-client-metadata.json"),
            ("two_tokens_1", None),
            ("two_tokens_2", None),
            ("diff_urls", None),
            ("same_url", "https://same-url.example.com/.well-known/oauth-client-metadata.json"),
            ("never_used", None),
            ("created_after_app", "https://created-after.example.com/.well-known/oauth-client-metadata.json"),
            ("already_bound", "https://already-bound.example.com/manual"),
            ("port_443", "https://port-443.example.com/.well-known/oauth-client-metadata.json"),
            ("trailing_slash", "https://trailing-slash.example.com/.well-known/oauth-client-metadata.json"),
        ]
    )
    def test_backfill_outcome(self, token_key: str, expected_cimd_url: str | None) -> None:
        token = self.CIMDVerificationToken.objects.get(pk=self.tokens[token_key].pk)
        assert token.cimd_url == expected_cimd_url
