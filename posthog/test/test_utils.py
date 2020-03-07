from django.test import TestCase
from posthog.utils import relative_date_parse
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