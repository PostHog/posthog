# Seeding, resetting and checking the demo

A demo needs data the flow can act on, the same starting point for every take, and proof that the flow works before the camera rolls.
Write three small scripts for each demo: seed, reset, and check.
Keep them outside the repo, for example in a `demo/` folder next to the storyboard.

## What the flow needs

List it before writing anything. Walk the flow once by hand, or read the code path, and note each thing that has to exist first:

- **Where it runs**: the demo user and project. `python manage.py setup_dev --no-data` gives `test@posthog.com` and one project, usually team 1.
- **What gates it**: feature flags, plan features, or settings that hide the UI or the endpoint.
- **What it starts from**: the objects on screen in the first step, such as a template, a dashboard, or a flag.
- **What it calls**: API keys and their scopes, verified integrations, or webhooks the flow needs.
- **What has to run**: workers, queues, and local services such as MailDev. The web app alone often is not enough. See [troubleshooting.md](troubleshooting.md).
- **What proves it worked**: the row, email, event, or metric the last steps show. Something has to produce it, so check that the process behind it runs.

## Seed

Create the starting state in one script, idempotent so a second run does no harm.
On a local stack, a Django shell script is the shortest path: it can create anything, including what the API refuses, such as a verified integration.

```bash
DEBUG=1 python manage.py shell < demo/seed.py > demo/seed.out
grep -E '^[A-Z_]+=' demo/seed.out > demo/demo.env
```

```python
# demo/seed.py: create what the flow starts from, then print what the storyboard needs as NAME=value.
from posthog.models import Team, User

team = Team.objects.order_by("id").first()
user = User.objects.first()

# 1. Gates: turn on the feature flag for the demo project.
# 2. Prerequisites: integrations, settings, API keys. Print new secrets once; nothing else stores them.
# 3. Starting objects: what the first step shows. Use invented names and example.com addresses.

print(f"TEAM={team.id}")
# print(f"TEMPLATE={template.id}")
# print(f"API_KEY={raw_key}")
```

Import models from the product that owns them, and use `get_or_create` so a rerun finds what the first run made.
When the app has an API for a step, calling it as the demo user exercises the same path as the UI. Use the shell for what the API cannot do.

The storyboard reads the printed values as `${NAME}`.
Pass them in the environment, and list secrets under `secrets` so the video shows `$NAME` instead of the value:

```bash
set -a; source demo/demo.env; set +a
uv run python .agents/skills/recording-demo-videos/scripts/record_demo.py demo/storyboard.json
```

Keep `demo.env` out of the repo. It holds working keys.

## Reset

A take changes state: it creates objects, sends emails, writes versions, and moves counters.
The reset script puts back the state the first step expects, so every take starts the same.

- Undo what the flow creates: delete the objects, unlink them, or restore the fields the flow edits.
- Clear outside state the video shows, such as the local inbox: `curl -s -X DELETE localhost:1080/email/all`.
- New objects start counters from zero. When the video shows a count, recreate the object rather than reuse it, because metrics and events that already exist stay attached to the old one.

Run it before every take, and make it print the state it left so a failed reset is visible:

```bash
bash demo/reset.sh && uv run python .agents/skills/recording-demo-videos/scripts/record_demo.py demo/storyboard.json
```

## Check

Run the flow once outside the recorder before the first take, then reset.
A failure is faster to find in a terminal than in a video.

- Call each endpoint the storyboard calls with `curl`, and check the status and the body.
- Check that the background work finished: the worker log, the row, the email in MailDev, the metric in ClickHouse.
- Open each page the storyboard visits, and check that the content each `wait_for` waits on appears.

When the recorder fails on a step, the log names it and `<output>.error.png` shows the screen. Fix the step, reset, and record again.

## Example

The transactional email demo needed:

- **Gates**: the feature flag that hides the send endpoint, created in team 1 at 100%.
- **Prerequisites**:
  - a verified email sender integration, set as the project's default sender
  - a project secret API key with the scope the endpoint checks
- **Starting objects**: an email template with a subject, a body and invented copy, plus a second template to show the library filter.
- **Running processes**:
  - the CDP workflow workers, which the default stack does not start
  - MailDev, to receive the email
- **Reset**: unlink the template from its workflow, delete the workflow, restore the edited subject, and clear MailDev.
- **Check**: one `curl` to the send endpoint returned `202`, and the email showed up in MailDev.
