from posthog.test.base import BaseTest
from unittest.mock import patch

from products.conversations.backend.tasks import embed_ticket


class TestEmbedTicketTask(BaseTest):
    @patch("products.conversations.backend.tasks.embed_conversations_ticket")
    def test_delegates_to_embed_conversations_ticket(self, mock_embed):
        embed_ticket.run(self.team.id, "ticket-abc")

        mock_embed.assert_called_once_with(self.team.id, "ticket-abc")
