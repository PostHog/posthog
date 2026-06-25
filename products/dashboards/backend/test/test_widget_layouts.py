from parameterized import parameterized

from products.dashboards.backend.widget_layouts import stack_widget_layout_at_bottom


class TestWidgetLayouts:
    """Backend placement only reads `layouts.sm`.

    New widgets are placed at the bottom, anchored to the tallest column so the grid's
    vertical compaction keeps them there; batch adds stack downward. Mobile (`xs`)
    placement is still derived on the frontend; the backend mirrors sm → xs for
    API/schema completeness.
    """

    @parameterized.expand(
        [
            # Tall column on the right: the new tile must span it (x=6), otherwise vertical
            # compaction would lift an x=0 tile up into the short left column's gap.
            (
                [{"x": 0, "y": 0, "w": 6, "h": 4}, {"x": 6, "y": 0, "w": 6, "h": 11}],
                {"x": 6, "y": 11, "w": 6, "h": 5},
            ),
            # Tall column on the left: anchoring at x=0 already spans it, so it stays put.
            (
                [{"x": 0, "y": 0, "w": 6, "h": 10}, {"x": 6, "y": 0, "w": 6, "h": 4}],
                {"x": 0, "y": 10, "w": 6, "h": 5},
            ),
        ]
    )
    def test_stack_widget_layout_at_bottom_anchors_to_tallest_column(
        self, existing: list[dict], expected_sm: dict
    ) -> None:
        layouts = stack_widget_layout_at_bottom(
            widget_type="error_tracking_list",
            existing_sm_layouts=existing,
        )

        assert layouts["sm"] == expected_sm
        assert layouts["xs"] == layouts["sm"]

    def test_stack_widget_layout_at_bottom_stacks_batch_below_tallest_column(self) -> None:
        # Batch adds stack downward in the tallest column's span so vertical compaction
        # keeps every new tile at the bottom (a horizontal row would drift up on a staircase).
        existing = [
            {"x": 0, "y": 0, "w": 6, "h": 4},
            {"x": 6, "y": 0, "w": 6, "h": 11},
        ]

        first = stack_widget_layout_at_bottom(
            widget_type="error_tracking_list",
            existing_sm_layouts=existing,
        )
        second = stack_widget_layout_at_bottom(
            widget_type="error_tracking_list",
            existing_sm_layouts=existing,
            pending_sm_layouts=[first["sm"]],
        )
        third = stack_widget_layout_at_bottom(
            widget_type="error_tracking_list",
            existing_sm_layouts=existing,
            pending_sm_layouts=[first["sm"], second["sm"]],
        )

        assert first["sm"] == {"x": 6, "y": 11, "w": 6, "h": 5}
        assert second["sm"] == {"x": 6, "y": 16, "w": 6, "h": 5}
        assert third["sm"] == {"x": 6, "y": 21, "w": 6, "h": 5}

    def test_stack_widget_layout_at_bottom_narrow_tile_anchors_to_tallest_column(self) -> None:
        # Tallest column is in the middle (x=8); a narrow new tile must overlap it so
        # compaction can't pull it above the true bottom.
        existing = [
            {"x": 0, "y": 0, "w": 6, "h": 3},
            {"x": 6, "y": 0, "w": 6, "h": 5},
            {"x": 8, "y": 5, "w": 4, "h": 9},
        ]

        layouts = stack_widget_layout_at_bottom(
            widget_type="error_tracking_list",
            existing_sm_layouts=existing,
        )

        placement = layouts["sm"]
        assert placement["y"] == 14
        # column span must include the tallest column (8)
        assert placement["x"] <= 8 < placement["x"] + placement["w"]

    def test_stack_widget_layout_at_bottom_stacks_batch_on_empty_dashboard(self) -> None:
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
        assert second["sm"] == {"x": 0, "y": 5, "w": 6, "h": 5}
