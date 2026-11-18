# Troubleshooting

Failures we hit while recording demos, and their fixes.

## The video shows minutes of spinners

The dev server compiles each frontend chunk on its first request, which can take a minute per page.
The recorder loads every `goto` page once before recording, and cuts each `goto` and `wait_for` wait from the final video.
When a page still loads in view, the step clicks before the data arrives. Add a `wait_for` on content that only exists once the data has loaded, such as a table row or a chart title.

## A step waits until it times out

- Two `wait_for` keys in one step: JSON keeps only the last one, so the step waits for the wrong thing. Split it into two steps.
- The target matches text that is not visible yet, or matches a hidden duplicate first. Use `"exact": true`, `"within"`, or `"nth"`.
- The data never arrives. Check the process behind it, below.

## The flow works in the app but not in the recording

The recorder logs in as `login`, which defaults to `test@posthog.com`.
Feature flags, seeded objects and API keys must belong to that user's workspace.

## A background job never runs

The default dev stack does not start every worker.
For example, workflow runs and email sends need the CDP workflow workers.
Start them next to the stack from the checkout:

```bash
(set -a; source .env.development; set +a; export NODEJS_CAPABILITY_GROUPS=cdp_workflows NODE_ENV=dev; \
  cd nodejs && nohup npx tsx src/index.ts > /tmp/node-workflows.log 2>&1 &)
```

Wait for `All systems go` in the log.
A job queued before the worker started runs as soon as it does, so reset and record again.

## Emails do not reach the local inbox

The local inbox is MailDev at `http://localhost:1080`.
Start it with `docker compose -f docker-compose.dev.yml up -d maildev` when the stack did not.
The email worker checks that the recipient's domain has mail servers and skips the send when it does not, so `example.com` recipients never arrive.
Use a domain with mail servers. MailDev catches the email, so nothing reaches the real address.

## Numbers in the video disagree with what happened

Metrics arrive through Kafka and ClickHouse, a few seconds after the action.
Wait for the chart or counter to load with a `wait_for`, and read the number in the contact sheet.
A local stack can count a workflow run twice. Its ClickHouse has two Kafka tables, `kafka_app_metrics2` and `kafka_app_metrics2_ws`, that read the same topic into `app_metrics2`.
ClickHouse drops most of the copies as duplicate inserts, but not all, so a count can come out one or two high.
When a number is off in a take, reset and record again rather than share it, or keep the counter out of the shot.

## The local stack lost its data

A cloud sandbox can restart, which stops the containers and can leave an empty database.
Run `hogli start -y -d` and `hogli wait`, then the seed script. Start any extra workers again.

## ElevenLabs calls fail

- `ELEVENLABS_API_KEY` missing: the recorder leaves out the voiceover and generated music, and lists them under `skipped_without_elevenlabs_key` in the log. A music `file` still plays. To add them, the developer sets the key in the shell. In a cloud task, add it as an environment variable of the task's environment in PostHog Desktop, under Settings and Environments. Never paste it into a storyboard or a commit.
- `401` or `quota_exceeded`: the key is wrong, lacks access to the endpoint, or the account ran out of credits. Takes already in the cache still work.
- A certificate error: the recorder uses `certifi`'s certificates, which the repo's Python environment has. Run it with `uv run python` from the checkout.

## Inline HTML is refused

The app's Content Security Policy refuses inline scripts and styles, and the cards and the overlay are both.
The recorder turns the policy off in its own browser context only, with Playwright's `bypass_csp`. The app is unchanged.

## A text field ignores the typing

Some fields are code editors rather than inputs, such as fields that accept Liquid.
Click the field, move the caret with `keys` (`Control+Home`, `Home`, `ArrowRight x10`), then type.
To find the field, a selector chain from its label works: `text=Subject >> nth=0 >> xpath=following-sibling::*[1]`.
