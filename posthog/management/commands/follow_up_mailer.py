from posthog.models import team
from posthog.models.follow_up_email import FollowUpEmail
from django.core.management.base import BaseCommand
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

from posthog.models import Team, Event

class Command(BaseCommand):
    help = 'Check user statuses and send email if necessary'

    def handle(self, *args, **options):
        all_teams = Team.objects.all()
        for team in all_teams:
            team_has_events = Event.objects.filter(team=team).exists()
            count = FollowUpEmail.objects.filter(team=team).count()
            if not team_has_events and count < 1:
                self._send_follow_up_to_team(team, count)

    def _send_follow_up_to_team(self, team: Team, count: int):
        for user in team.users.all():
            self._send_follow_up_to_user(user.email)
        
        FollowUpEmail.objects.create(team=team)
    
    def _send_follow_up_to_user(self, email: str):
        message = Mail(
            from_email='eric@posthog.com',
            to_emails=email,
            subject='Sending with Twilio SendGrid is Fun',
            html_content='<strong>and easy to do anywhere, even with Python</strong>')
        try:
            sg = SendGridAPIClient('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')
            response = sg.send(message)
            print(response.status_code)
            print(response.body)
            print(response.headers)
        except Exception as e:
            print(e.body)