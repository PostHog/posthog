"""Size limits for a ticket brief.

A brief is a ten-second read, and the writer is an agent, so a field without a cap grows
until it is no faster to read than the ticket.

The caps match the lengths that `products/conversations/skills/writing-posthog-support-tickets`
gives an agent that writes a ticket, so a ticket written to that shape fits the brief without
clipping. Change both together.
"""

MAX_AFFECTED_ITEMS = 5
MAX_ALREADY_ANSWERED = 300
MAX_AREA = 80
MAX_ASK = 400
MAX_ERROR_MESSAGE = 600
MAX_FACTS = 3
MAX_FACT = 160
MAX_ITEM_LABEL = 120
MAX_PURPOSE = 300
MAX_QUESTIONS = 3
MAX_QUESTION = 200
MAX_SCREENSHOTS = 5
MAX_SUPPORT_REASON = 300
MAX_TRIED = 5
MAX_URL_LENGTH = 2000
MAX_WHERE_STOPPED = 300
