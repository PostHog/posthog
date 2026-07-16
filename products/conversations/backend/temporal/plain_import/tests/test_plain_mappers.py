from parameterized import parameterized

from products.conversations.backend.models.constants import Channel, Priority, Status
from products.conversations.backend.temporal.plain_import.mappers import (
    extract_entry_body,
    map_plain_author_type,
    map_plain_channel_source,
    map_plain_priority,
    map_plain_status,
)


class TestPlainMappers:
    @parameterized.expand(
        [
            ("TODO", Status.OPEN),
            ("SNOOZED", Status.ON_HOLD),
            ("DONE", Status.RESOLVED),
            ("unknown", Status.OPEN),
            (None, Status.NEW),
        ]
    )
    def test_map_plain_status(self, raw: str | None, expected: str) -> None:
        assert map_plain_status(raw) == expected

    @parameterized.expand(
        [
            (0, Priority.HIGH),
            (1, Priority.HIGH),
            (2, Priority.MEDIUM),
            (3, Priority.LOW),
            (None, None),
        ]
    )
    def test_map_plain_priority(self, raw: int | None, expected: str | None) -> None:
        assert map_plain_priority(raw) == expected

    @parameterized.expand(
        [
            ("EMAIL", Channel.EMAIL),
            ("CHAT", Channel.WIDGET),
            ("SLACK", Channel.SLACK),
            ("MS_TEAMS", Channel.TEAMS),
            ("DISCORD", Channel.WIDGET),
            ("API", Channel.EMAIL),
            (None, Channel.EMAIL),
        ]
    )
    def test_map_plain_channel_source(self, raw: str | None, expected: str) -> None:
        assert map_plain_channel_source(raw) == expected

    @parameterized.expand(
        [
            ("customer", "CustomerActor", "EmailEntry", "customer", False),
            ("support_user", "UserActor", "EmailEntry", "support", False),
            ("machine", "MachineUserActor", "ChatEntry", "support", False),
            ("system", "SystemActor", "CustomEntry", "support", False),
            ("note", "UserActor", "NoteEntry", "support", True),
            ("note_customer_actor", "CustomerActor", "NoteEntry", "support", True),
            ("unknown", None, "EmailEntry", "support", False),
        ]
    )
    def test_map_plain_author_type(
        self,
        _name: str,
        actor_typename: str | None,
        entry_typename: str | None,
        author_type: str,
        is_private: bool,
    ) -> None:
        assert map_plain_author_type(actor_typename=actor_typename, entry_typename=entry_typename) == (
            author_type,
            is_private,
        )

    def test_extract_email_entry_body(self) -> None:
        body = extract_entry_body(
            {
                "__typename": "EmailEntry",
                "subject": "Help",
                "fullMarkdownContent": "Please help me",
            }
        )
        assert body == "Help\n\nPlease help me"

    def test_extract_note_entry_body(self) -> None:
        assert extract_entry_body({"__typename": "NoteEntry", "markdown": "Internal note"}) == "Internal note"

    def test_extract_discord_entry_body(self) -> None:
        assert (
            extract_entry_body({"__typename": "DiscordMessageEntry", "markdownContent": "Discord msg"}) == "Discord msg"
        )
