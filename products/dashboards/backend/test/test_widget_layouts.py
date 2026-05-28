from products.dashboards.backend.widget_layouts import stack_widget_layout_at_bottom


def _max_layout_bottom(sm_layouts: list[dict[str, int]]) -> int:
    return max(layout["y"] + layout["h"] for layout in sm_layouts)


class TestWidgetLayouts:
    """Backend stacking only reads `layouts.sm`.

    Mobile (`xs`) placement is derived on the frontend in `tileLayouts.calculateLayouts`:
    stored xs is ignored, tiles are single-column, and order/height follow sm layout.
    The backend still mirrors sm → xs for API/schema completeness; dashboard save paths
    only persist sm anyway.
    """

    def test_stack_widget_layout_at_bottom_stacks_after_existing_and_pending(self) -> None:
        # Messy dashboard grid: mixed widths/heights, side-by-side rows, one full-width strip.
        # Deepest existing tile is the tall insight on the right (y=11, h=7 → bottom 18).
        existing = [
            {"x": 0, "y": 0, "w": 6, "h": 4},  # top-left widget
            {"x": 6, "y": 0, "w": 6, "h": 9},  # tall insight, right column
            {"x": 0, "y": 4, "w": 3, "h": 2},  # small text card
            {"x": 3, "y": 4, "w": 3, "h": 5},  # medium insight under top-left
            {"x": 0, "y": 9, "w": 12, "h": 2},  # full-width header strip
            {"x": 0, "y": 11, "w": 4, "h": 3},  # short widget, left
            {"x": 4, "y": 11, "w": 8, "h": 7},  # tallest tile — sets existing max bottom (18)
        ]
        # Earlier widgets from the same batch add, stacked below the grid.
        pending = [
            {"x": 0, "y": 18, "w": 6, "h": 4},
            {"x": 0, "y": 22, "w": 6, "h": 3},
        ]

        layouts = stack_widget_layout_at_bottom(
            widget_type="error_tracking_list",
            existing_sm_layouts=existing,
            pending_sm_layouts=pending,
        )

        expected_y = _max_layout_bottom([*existing, *pending])
        assert expected_y == 25
        assert layouts["sm"] == {"x": 0, "y": expected_y, "w": 6, "h": 5}
        assert layouts["xs"] == layouts["sm"]

    def test_stack_widget_layout_at_bottom_ignores_horizontal_position(self) -> None:
        # A wide tile parked on the far right still contributes its bottom edge.
        existing = [
            {"x": 0, "y": 0, "w": 4, "h": 3},
            {"x": 8, "y": 2, "w": 4, "h": 10},  # bottom 12 despite x=8
            {"x": 4, "y": 6, "w": 2, "h": 2},
        ]

        layouts = stack_widget_layout_at_bottom(
            widget_type="session_replay_list",
            existing_sm_layouts=existing,
        )

        assert layouts["sm"]["y"] == 12
        assert layouts["sm"]["w"] == 6
        assert layouts["sm"]["h"] == 5

    def test_stack_widget_layout_at_bottom_does_not_consider_stored_xs_layouts(self) -> None:
        # Templates may persist xs with w=1 and deep y values; stacking ignores them.
        # Mobile reflow is handled client-side from sm order + sm.h.
        existing = [
            {"x": 0, "y": 0, "w": 6, "h": 4},
            {"x": 6, "y": 0, "w": 6, "h": 11},
        ]

        layouts = stack_widget_layout_at_bottom(
            widget_type="error_tracking_list",
            existing_sm_layouts=existing,
        )

        assert layouts["sm"]["y"] == 11
        assert layouts["xs"] == layouts["sm"]
