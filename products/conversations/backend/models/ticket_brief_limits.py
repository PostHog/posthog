"""Size limits for a ticket brief.

Here rather than beside the serializer so the Temporal activity can read them without
importing the API package, which imports the activity's own caller back.
"""

MAX_AFFECTED_ITEMS = 5
MAX_ASK = 400
MAX_AREA = 80
MAX_ERROR_MESSAGE = 600
MAX_FACTS = 5
MAX_FACT = 160
MAX_ITEM_LABEL = 120
MAX_PURPOSE = 300
MAX_QUESTIONS = 6
MAX_QUESTION = 200
MAX_SCREENSHOTS = 5
MAX_TRIED = 5
MAX_URL_LENGTH = 2000
