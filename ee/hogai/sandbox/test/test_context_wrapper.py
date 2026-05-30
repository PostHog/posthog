import pytest
from unittest import TestCase

from parameterized import parameterized

from ee.hogai.sandbox.context_wrapper import AttachedContext, prune_repeated_entity_refs, wrap_user_message


@pytest.mark.usefixtures("unittest_snapshot")
class TestContextWrapper(TestCase):
    snapshot: object

    @parameterized.expand(
        [
            (
                "empty",
                [],
            ),
            (
                "one_of_each",
                [
                    AttachedContext(type="dashboard", id=123, name="Marketing Funnel"),
                    AttachedContext(type="insight", id="abc-def", name="Daily Signups"),
                    AttachedContext(type="event", id="pageview", name="$pageview"),
                    AttachedContext(type="action", id=7, name="Signed up"),
                    AttachedContext(
                        type="error_tracking_issue",
                        id="019249ab-0000-7000-8000-000000000000",
                        name="TypeError in checkout flow",
                    ),
                    AttachedContext(type="evaluation", id=42, name="Tone eval"),
                    AttachedContext(type="notebook", id="nb-1", name="Weekly review"),
                    AttachedContext(type="text", value="I think this regressed last Thursday"),
                ],
            ),
            (
                "mixed_with_text",
                [
                    AttachedContext(type="dashboard", id=123, name="Marketing Funnel"),
                    AttachedContext(type="text", value="Compare to last week"),
                    AttachedContext(type="insight", id="xyz", name="Conversion by source"),
                ],
            ),
            (
                "missing_name",
                [
                    AttachedContext(type="dashboard", id=123),
                    AttachedContext(type="insight", id="abc"),
                ],
            ),
        ]
    )
    def test_wrap_user_message_renders_block(self, _name: str, attached: list[AttachedContext]) -> None:
        result = wrap_user_message("Why did conversions drop?", attached)
        assert result == self.snapshot

    def test_wrap_user_message_returns_content_unchanged_on_empty_list(self) -> None:
        content = "Why did conversions drop?"
        assert wrap_user_message(content, []) == content

    def test_length_capped_text_renders_full_value(self) -> None:
        # The wrapper itself does not cap — capping is the serializer's job. The wrapper renders
        # whatever it is given, so a long-but-bounded value still produces a deterministic block.
        long_value = "x" * 4096
        result = wrap_user_message("look", [AttachedContext(type="text", value=long_value)])
        assert long_value in result
        assert result.startswith("<posthog_context>")

    def test_prune_drops_repeated_entity_refs(self) -> None:
        attached = [
            AttachedContext(type="dashboard", id=123, name="Marketing Funnel"),
            AttachedContext(type="insight", id="abc", name="Daily Signups"),
        ]
        pruned = prune_repeated_entity_refs(attached, prior=[("dashboard", 123)])
        assert [(item.type, item.id) for item in pruned] == [("insight", "abc")]

    def test_prune_deduplicates_within_the_same_batch(self) -> None:
        attached = [
            AttachedContext(type="dashboard", id=123),
            AttachedContext(type="dashboard", id=123),
        ]
        pruned = prune_repeated_entity_refs(attached, prior=[])
        assert len(pruned) == 1

    def test_prune_never_deduplicates_text_items(self) -> None:
        attached = [
            AttachedContext(type="text", value="error snippet"),
            AttachedContext(type="text", value="error snippet"),
        ]
        pruned = prune_repeated_entity_refs(attached, prior=[])
        assert len(pruned) == 2
        assert all(item.type == "text" for item in pruned)

    def test_prune_keeps_entity_without_id(self) -> None:
        attached = [AttachedContext(type="dashboard", name="no id")]
        pruned = prune_repeated_entity_refs(attached, prior=[])
        assert len(pruned) == 1
