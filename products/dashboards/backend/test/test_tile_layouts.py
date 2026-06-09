from parameterized import parameterized

from products.dashboards.backend.tile_layouts import stack_tile_layout_at_bottom


class TestStackTileLayoutAtBottom:
    """Lowest-segment greedy placement, mirroring how the frontend places tiles without a stored layout."""

    @parameterized.expand(
        [
            ("empty_dashboard", [], {"x": 0, "y": 0, "w": 6, "h": 5}),
            (
                "fills_gap_beside_existing_tile",
                [{"x": 0, "y": 0, "w": 6, "h": 5}],
                {"x": 6, "y": 0, "w": 6, "h": 5},
            ),
            (
                "wraps_to_next_row_when_row_full",
                [{"x": 0, "y": 0, "w": 6, "h": 5}, {"x": 6, "y": 0, "w": 6, "h": 5}],
                {"x": 0, "y": 5, "w": 6, "h": 5},
            ),
            (
                "picks_lowest_segment_under_uneven_columns",
                [{"x": 0, "y": 0, "w": 6, "h": 8}, {"x": 6, "y": 0, "w": 6, "h": 3}],
                {"x": 6, "y": 3, "w": 6, "h": 5},
            ),
        ]
    )
    def test_placement(self, _name: str, existing: list[dict[str, int]], expected_sm: dict[str, int]) -> None:
        layouts = stack_tile_layout_at_bottom(existing_sm_layouts=existing)

        assert layouts["sm"] == expected_sm
        assert layouts["xs"] == layouts["sm"]

    def test_custom_size_is_clamped_to_grid(self) -> None:
        layouts = stack_tile_layout_at_bottom(existing_sm_layouts=[], width=20, height=0)

        assert layouts["sm"] == {"x": 0, "y": 0, "w": 12, "h": 1}
