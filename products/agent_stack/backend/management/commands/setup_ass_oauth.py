"""Register an OAuth application for the `ass` CLI to log into a local PostHog.

Cloud has a built-in client_id baked into the CLI; for a local instance the
admin has to register one. Run this once after `migrate` to make
`ASS_POSTHOG_URL=http://localhost:8000 ass login` work.

Keep `client_id` in sync with the CLI's `ASS_POSTHOG_OAUTH_CLIENT_ID` env var
(see packages/ass-cli/src/posthog/constants.ts).
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.models import OAuthApplication

# Public client_id for the ass CLI's local-PostHog OAuth flow. Stable across
# devs so the same env var works everywhere.
ASS_CLI_CLIENT_ID_DEV = "ass-cli-local-dev"

# All the loopback ports the CLI tries in order. Registering them all means a
# port collision with another dev tool just falls through to the next one.
_ASS_CLI_REDIRECT_URIS = " ".join(f"http://localhost:{port}/callback" for port in (8239, 8238, 8240, 8237, 8236, 8235))


class Command(BaseCommand):
    help = "Create the OAuth application the ass CLI uses for local PostHog logins"

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command can only be run with DEBUG=1")

        app, created = OAuthApplication.objects.get_or_create(
            client_id=ASS_CLI_CLIENT_ID_DEV,
            defaults={
                "name": "ass CLI (local dev)",
                "client_type": OAuthApplication.CLIENT_PUBLIC,
                "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
                "redirect_uris": _ASS_CLI_REDIRECT_URIS,
                "algorithm": "RS256",
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f"Created OAuthApplication '{app.name}' (client_id={app.client_id})"))
        else:
            self.stdout.write(self.style.SUCCESS(f"OAuthApplication '{app.name}' already exists"))
        self.stdout.write(
            self.style.NOTICE(
                "Run the CLI with:\n"
                f"  ASS_POSTHOG_URL=http://localhost:8000 ASS_POSTHOG_OAUTH_CLIENT_ID={app.client_id} ass login"
            )
        )
