from ee.dynamodb.events import create_events_table, destroy_events_table


class DynamodbTestMixin:
    def tearDown(self):
        try:
            self._destroy_event_table()
            self._create_event_table()
        except:
            pass

    def _destroy_event_table(self):
        destroy_events_table()

    def _create_event_table(self):
        create_events_table()
