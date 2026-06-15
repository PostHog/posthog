from products.dashboards.backend.widget_layouts import stack_widget_layout_at_bottom


class TestWidgetLayouts:
    """Backend placement only reads `layouts.sm`.

    New widgets append to the bottom row of the dashboard (below the tallest tile),
    packing batch adds horizontally on that row. Mobile (`xs`) placement is still
    derived on the frontend; the backend mirrors sm → xs for API/schema completeness.
    """

    def test_stack_widget_layout_at_bottom_appends_below_tallest_tile(self) -> None:
        existing = [
            {"x": 0, "y": 0, "w": 6, "h": 4},
            {"x": 6, "y": 0, "w": 6, "h": 11},
        ]

        layouts = stack_widget_layout_at_bottom(
            widget_type="error_tracking_list",
            existing_sm_layouts=existing,
        )

        assert layouts["sm"] == {"x": 0, "y": 11, "w": 6, "h": 5}
        assert layouts["xs"] == layouts["sm"]

    def test_stack_widget_layout_at_bottom_packs_batch_on_same_row(self) -> None:
        existing = [
            {"x": 0, "y": 0, "w": 6, "h": 4},
            {"x": 6, "y": 0, "w": 6, "h": 9},
            {"x": 0, "y": 4, "w": 3, "h": 2},
            {"x": 3, "y": 4, "w": 3, "h": 5},
            {"x": 0, "y": 9, "w": 12, "h": 2},
            {"x": 0, "y": 11, "w": 4, "h": 3},
            {"x": 4, "y": 11, "w": 8, "h": 7},
        ]
        pending = [
            {"x": 0, "y": 18, "w": 6, "h": 4},
            {"x": 0, "y": 22, "w": 6, "h": 3},
        ]

        layouts = stack_widget_layout_at_bottom(
            widget_type="error_tracking_list",
            existing_sm_layouts=existing,
            pending_sm_layouts=pending,
        )

        assert layouts["sm"] == {"x": 6, "y": 18, "w": 6, "h": 5}

    def test_stack_widget_layout_at_bottom_ignores_short_column_gaps(self) -> None:
        existing = [
            {"x": 0, "y": 0, "w": 6, "h": 10},
            {"x": 6, "y": 0, "w": 6, "h": 4},
        ]

        layouts = stack_widget_layout_at_bottom(
            widget_type="error_tracking_list",
            existing_sm_layouts=existing,
        )

        assert layouts["sm"] == {"x": 0, "y": 10, "w": 6, "h": 5}

    def test_stack_widget_layout_at_bottom_packs_batch_side_by_side(self) -> None:
        first = stack_widget_layout_at_bottom(
            widget_type="error_tracking_list",
            existing_sm_layouts=[],
        )
        second = stack_widget_layout_at_bottom(
            widget_type="error_tracking_list",
            existing_sm_layouts=[],
            pending_sm_layouts=[first["sm"]],
        )

        assert first["sm"] == {"x": 0, "y": 0, "w": 6, "h": 5}
        assert second["sm"] == {"x": 6, "y": 0, "w": 6, "h": 5}

    def test_stack_widget_layout_at_bottom_wraps_to_next_row_when_bottom_row_full(self) -> None:
        existing = [
            {"x": 0, "y": 0, "w": 6, "h": 5},
            {"x": 6, "y": 0, "w": 6, "h": 5},
        ]
        pending = [
            {"x": 0, "y": 0, "w": 6, "h": 5},
            {"x": 6, "y": 0, "w": 6, "h": 5},
        ]

        layouts = stack_widget_layout_at_bottom(
            widget_type="error_tracking_list",
            existing_sm_layouts=existing,
            pending_sm_layouts=pending,
        )

        assert layouts["sm"] == {"x": 0, "y": 5, "w": 6, "h": 5}
