from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from dateutil.relativedelta import relativedelta

from posthog.models import Event, Element, Team, Person

class Command(BaseCommand):
    help = 'Creates fake demo data'

    def add_arguments(self, parser):
        parser.add_argument('team_id', nargs='+', type=int)

    def handle(self, *args, **options):
        team = Team.objects.get(pk=options['team_id'][0])

        # delete data
        Event.objects.filter(team=team).delete()
        Person.objects.filter(team=team).delete()

        now = timezone.now()

        Person.objects.create(distinct_ids=['john.smith@gmail.com'], team=team)

        for i in range(0, 10):
            event = Event.objects.create(distinct_id='john.smith@gmail.com', team=team, event='$autocapture', properties={'$current_url': 'http://127.0.0.1:8000/demo/1'})
            # Hack to change the timestamp with a different date
            Event.objects.filter(event=event).update(timestamp=now - relativedelta(days=i))
            Element.objects.create(event=event, order=0, tag_name='button', attr_class=['btn', 'btn-success'], text='Sign up!')
            Element.objects.create(event=event, order=1, tag_name='form', attributes={'action': '/demo/2'})
            Element.objects.create(event=event, order=2, tag_name='div', attr_class=['container'])
            Element.objects.create(event=event, order=3, tag_name='body')

            Event.objects.create(distinct_id='john.smith@gmail.com', team=team, event='$pageview', properties={'$current_url': 'http://127.0.0.1:8000/demo/1'})
