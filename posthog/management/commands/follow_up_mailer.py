from posthog.models import team
from posthog.models.follow_up_email import FollowUpEmail
from django.core.management.base import BaseCommand
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

from posthog.models import Team, Event
from django.conf import settings

class Command(BaseCommand):
    help = 'Check user statuses and send email if necessary'

    def handle(self, *args, **options):
        all_teams = Team.objects.all()
        for team in all_teams:
            team_has_events = Event.objects.filter(team=team).exists()
            count = FollowUpEmail.objects.filter(team=team).count()
            if not team_has_events:
                self._send_follow_up_to_team(team, count)

    def _send_follow_up_to_team(self, team: Team, count: int):
        for user in team.users.all():
            self._send_follow_up_to_user(user.email)
        
        FollowUpEmail.objects.create(team=team)
    
    def _send_follow_up_to_user(self, email: str):
        message = Mail(
            from_email='eric@posthog.com',
            to_emails=email,
            subject='Follow Up Email',
            html_content='Looks like you haven\'t started sending events with Posthog yet. Want a demo?')
        try:
            if settings.SENDGRID_API_KEY:
                sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
            else: 
                raise Exception("No Sendgrid Key")
            sg.send(message)
        except Exception as e:
            print(e.body)