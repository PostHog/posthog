import unittest

from products.ai_observability.backend.dashboard_templates import get_ai_observability_default_template


class TestAIObservabilityDefaultTemplate(unittest.TestCase):
    def setUp(self) -> None:
        self.tiles = {tile["name"]: tile["query"]["source"] for tile in get_ai_observability_default_template().tiles}

    def test_trace_and_user_tiles_count_the_whole_ai_event_family(self) -> None:
        # A project sending spans and traces but no generations must still see rows on these
        # tiles, so they match the `$ai_*` family by prefix rather than `$ai_generation` alone.
        for name in ["Traces", "Generative AI users"]:
            source = self.tiles[name]
            self.assertTrue(all(series["event"] is None for series in source["series"]), name)
            self.assertIn({"type": "hogql", "key": "event like '$ai_%'"}, source["properties"], name)

    def test_no_tile_filters_on_missing_distinct_id(self) -> None:
        # The `distinct_id != properties.$ai_trace_id` filter blanked the per-user tiles for any
        # project that does not set `distinct_id`. It must not return to any tile.
        for name, source in self.tiles.items():
            keys = [prop.get("key") for prop in source["properties"]]
            self.assertNotIn("distinct_id != properties.$ai_trace_id", keys, name)
