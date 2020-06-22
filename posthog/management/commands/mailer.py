from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from dateutil.relativedelta import relativedelta

from django.forms.models import model_to_dict
from django.db import transaction, models

from posthog.models import Team, Event, Element, ElementGroup

class Command(BaseCommand):
    help = 'Check user statuses and send email if necessary'

    def handle(self, *args, **options):
        all_teams = Team.objects.all()
        for team in all_teams:
            team_has_events = Event.objects.filter(team=team).exists()
            if not team_has_events:
                print("They don't have events:", team.pk)