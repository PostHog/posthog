# Conversations

## Customer communication email

A Customer Analytics Google account connection grants read access to Calendar and Gmail. The hourly sync imports customer meetings and messages from Inbox and Sent into matching accounts. The first run imports up to 100 messages from the previous 30 days. Later runs use the Gmail history cursor and do not store internal-only messages.

## Management commands

### `run_support_reply`

Run the grounded support reply pipeline for a single ticket (useful for dogfooding).

```bash
# By ticket number (easier to find in the UI)
python manage.py run_support_reply --team-id 1 --ticket-number 42

# By ticket UUID
python manage.py run_support_reply --team-id 1 --ticket-id "a1b2c3d4-..."
```
