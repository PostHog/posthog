# ruff: noqa: T201 allow print statements

from django.core.management.base import BaseCommand

from posthog.models import Team


class Command(BaseCommand):
    help = "Get project API keys through command line instead of having to go through settings"

    def handle(self, *args, **options):
        for team in Team.objects.all():
            print(f"{team.name + ' ' if team.name else ''}(ID {team.id}) - {team.api_token}")
