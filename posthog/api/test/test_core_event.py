from posthog.test.base import APIBaseTest

from posthog.models.core_event import CoreEvent


class TestCoreEventAPI(APIBaseTest):
    def test_list_pages_do_not_repeat_or_drop_events_with_tied_timestamps(self) -> None:
        CoreEvent.objects.bulk_create(
            CoreEvent(
                team=self.team,
                name=f"Core event {index}",
                category=CoreEvent.Category.ACTIVATION,
                filter={"kind": "EventsNode", "event": "$pageview"},
            )
            for index in range(105)
        )
        CoreEvent.objects.filter(team=self.team).update(created_at="2026-01-01T00:00:00Z")

        url = f"/api/environments/{self.team.id}/core_events/"
        first_page = self.client.get(url).json()

        # A write between the two requests moves the row in the heap, so an order that breaks
        # no tie hands the same row back on both pages and drops another.
        CoreEvent.objects.filter(id=first_page["results"][0]["id"]).update(name="Renamed")

        second_page = self.client.get(f"{url}?offset=100").json()

        returned_ids = [event["id"] for event in first_page["results"] + second_page["results"]]
        assert len(returned_ids) == 105
        assert len(set(returned_ids)) == 105
