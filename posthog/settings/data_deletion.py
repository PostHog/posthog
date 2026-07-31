import os

# Incoming webhook for the channel where the ClickHouse Team reviews data deletion requests.
# Unset by default — leaving it empty makes the notification a no-op.
DATA_DELETION_SLACK_WEBHOOK_URL: str = os.getenv("DATA_DELETION_SLACK_WEBHOOK_URL", "")
