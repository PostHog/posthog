import logging

from django.conf import settings
from django.core.management.commands.shell import Command as DjangoShellCommand


class Command(DjangoShellCommand):
    """Quieter `manage.py shell`.

    Startup logging is forced to ERROR in settings while an interactive shell is
    detected (see posthog/settings/logs.py), keeping app-ready noise out of the
    prompt. Restore the normal level here — right before the REPL opens — so
    logging behaves as usual inside the session.

    Django 5.2 prints "N objects imported automatically" at verbosity >= 1. Treat
    the default (1) as quiet; the auto-imports still happen, just silently. Pass
    `-v 2` to see the full import list.
    """

    def handle(self, **options):
        logging.getLogger().setLevel(settings.SHELL_LOG_LEVEL)
        if options.get("verbosity") == 1:
            options["verbosity"] = 0
        return super().handle(**options)
