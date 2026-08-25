# Conversations

## Customer communication email

### Google account sync

A Customer Analytics Google account connection grants read access to Calendar and Gmail. The hourly sync imports customer meetings and messages from Inbox and Sent into matching accounts. The first run imports up to 100 messages from the previous 30 days. Later runs use the Gmail history cursor and do not store internal-only messages.

### Email forwarding

Customer communication channels use a unique PostHog forwarding address. New channels remain pending until their owner completes Gmail forwarding confirmation.

While setup is pending, the inbound webhook discards normal email. It stores only a short-lived Google confirmation action after Mailgun verifies the webhook, Google SPF and DKIM pass, the source mailbox matches the channel, and the action uses the expected Google host. The encrypted setup record is visible only through the owner-scoped setup flow and is deleted after use or expiration.

After confirmation, incoming messages are stored as email threads. Customer Analytics links those threads to matching accounts before exposing them in the account view.

## Management commands

### `run_support_reply`

Run the grounded support reply pipeline for a single ticket (useful for dogfooding).

```bash
# By ticket number (easier to find in the UI)
python manage.py run_support_reply --team-id 1 --ticket-number 42

# By ticket UUID
python manage.py run_support_reply --team-id 1 --ticket-id "a1b2c3d4-..."
```
