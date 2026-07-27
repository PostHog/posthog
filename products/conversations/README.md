# Conversations

## Management commands

### `run_support_reply`

Run the grounded support reply pipeline for a single ticket (useful for dogfooding).

```bash
# By ticket number (easier to find in the UI)
python manage.py run_support_reply --team-id 1 --ticket-number 42

# By ticket UUID
python manage.py run_support_reply --team-id 1 --ticket-id "a1b2c3d4-..."
```
