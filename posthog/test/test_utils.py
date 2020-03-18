from django.test import TestCase
from posthog.models import Event
from posthog.api.test.base import BaseTest
from posthog.utils import relative_date_parse, properties_to_Q
from freezegun import freeze_time # type: ignore

class TestRelativeDateParse(TestCase):
    @freeze_time('2020-01-31')
    def test_day(self):
        self.assertEqual(relative_date_parse('dStart').strftime("%Y-%m-%d"), '2020-01-31')
        self.assertEqual(relative_date_parse('-1d').strftime("%Y-%m-%d"), '2020-01-30')
        self.assertEqual(relative_date_parse('-2d').strftime("%Y-%m-%d"), '2020-01-29')

    @freeze_time('2020-01-31')
    def test_month(self):
        self.assertEqual(relative_date_parse('-1m').strftime("%Y-%m-%d"), '2019-12-31')
        self.assertEqual(relative_date_parse('-2m').strftime("%Y-%m-%d"), '2019-11-30')

        self.assertEqual(relative_date_parse('mStart').strftime("%Y-%m-%d"), '2020-01-01')
        self.assertEqual(relative_date_parse('-1mStart').strftime("%Y-%m-%d"), '2019-12-01')
        self.assertEqual(relative_date_parse('-2mStart').strftime("%Y-%m-%d"), '2019-11-01')

        self.assertEqual(relative_date_parse('-1mEnd').strftime("%Y-%m-%d"), '2019-12-31')
        self.assertEqual(relative_date_parse('-2mEnd').strftime("%Y-%m-%d"), '2019-11-30')

    @freeze_time('2020-01-31')
    def test_year(self):
        self.assertEqual(relative_date_parse('-1y').strftime("%Y-%m-%d"), '2019-01-31')
        self.assertEqual(relative_date_parse('-2y').strftime("%Y-%m-%d"), '2018-01-31')

        self.assertEqual(relative_date_parse('yStart').strftime("%Y-%m-%d"), '2020-01-01')
        self.assertEqual(relative_date_parse('-1yStart').strftime("%Y-%m-%d"), '2019-01-01')

    @freeze_time('2020-01-31')
    def test_normal_date(self):
        self.assertEqual(relative_date_parse('2019-12-31').strftime("%Y-%m-%d"), '2019-12-31')

class TestPropertiesToQ(BaseTest):
    def test_simple(self):
        Event.objects.create(team=self.team, event='$pageview')
        Event.objects.create(team=self.team, event='$pageview', properties={'$current_url': 'https://whatever.com'})
        properties = {'$current_url': 'https://whatever.com'}
        events = Event.objects.filter(properties_to_Q(properties))
        self.assertEqual(events.count(), 1)

    def test_contains(self):
        Event.objects.create(team=self.team, event='$pageview')
        event2 = Event.objects.create(team=self.team, event='$pageview', properties={'$current_url': 'https://whatever.com'})
        properties = {'$current_url__icontains': 'whatever'}
        events = Event.objects.filter(properties_to_Q(properties))
        self.assertEqual(events.get(), event2)

    def test_is_not(self):
        event1 = Event.objects.create(team=self.team, event='$pageview')
        event2 = Event.objects.create(team=self.team, event='$pageview', properties={'$current_url': 'https://something.com'})
        Event.objects.create(team=self.team, event='$pageview', properties={'$current_url': 'https://whatever.com'})
        properties = {'$current_url__is_not': 'https://whatever.com'}
        events = Event.objects.filter(properties_to_Q(properties))
        self.assertEqual(events[0], event1)
        self.assertEqual(events[1], event2)
        self.assertEqual(len(events), 2)

    def test_does_not_contain(self):
        event1 = Event.objects.create(team=self.team, event='$pageview')
        event2 = Event.objects.create(team=self.team, event='$pageview', properties={'$current_url': 'https://something.com'})
        Event.objects.create(team=self.team, event='$pageview', properties={'$current_url': 'https://whatever.com'})
        properties = {'$current_url__not_icontains': 'whatever.com'}
        events = Event.objects.filter(properties_to_Q(properties))
        self.assertEqual(events[0], event1)
        self.assertEqual(events[1], event2)
        self.assertEqual(len(events), 2)