# hog agent evals

These evals run coding agents through `hog setup` and `hog skills` in [StuntHog](https://github.com/PostHog/stunthog), against a fake PostHog. They check that agents follow hog's instructions, hand the login to the user correctly, and pick the right skills.

## How it works

- Each session runs in a Docker container with the released hog and hog-worker, installed with `install.sh`.
- The container sends its HTTPS traffic through a mitmproxy at `host.docker.internal`. The proxy answers for `us.posthog.com`, `eu.posthog.com`, their ingestion hosts, and hog's release manifest, and never reaches the real PostHog. Other traffic passes through unchanged, so skills come from the real GitHub releases.
- The proxy listens on `127.0.0.1` only, which Docker Desktop forwards `host.docker.internal` to. On Linux Docker Engine, start it with `HOG_MOCK_BIND` and `HOG_MOCK_HOST` set to the `docker0` address, such as `172.17.0.1`.
- `start.sh` pins the hog release manifest and downloads hog's API catalog once, so `hog api` works against the fake project.
- hog keeps its default host, so agents see the same region notes and login links as a real user.
- The proxy port picks the scenario. Each environment's Dockerfile points `HTTPS_PROXY` at one port.

| Scenario  | Port  | What the fake user does                             | Events at verify |
| --------- | ----- | --------------------------------------------------- | ---------------- |
| `approve` | 18080 | Approves the login 4 seconds after it starts        | 12               |
| `never`   | 18081 | Never approves                                      | 0                |
| `denied`  | 18082 | Rejects the login                                   | 0                |
| `quiet`   | 18083 | Approves the login, and the app sends no events yet | 0                |

Every approved login gets a new project, as for someone who just signed up. Product intents, project setting changes, other API calls and hog's own telemetry go to `.generated/logs/requests.jsonl`.

StuntHog has no simulated user, so an agent can't get a reply mid-session. The `handoff` eval checks that the agent ends its turn with the right link. The other setup evals use a persona that approves any link right away, so the agent can finish in one turn.

## Run them

You need Docker, Bun, and StuntHog running with an OpenRouter key saved under **API keys**. The default models run through StuntHog's Pi harness on that key. `claude` and `codex` need Anthropic and OpenAI keys, and `opencode` needs OpenCode installed on the host.

```sh
hog/evals/mock/start.sh                 # fake PostHog, plus Dockerfiles for the latest hog
HOG_VERSION=0.2.0 hog/evals/mock/start.sh
bun hog/evals/stunthog.ts               # create or update the evals
bun hog/evals/stunthog.ts --run --only replay,eu --count 3
bun hog/evals/report.ts                 # scores and failed criteria for the latest run of each eval
bun hog/evals/report.ts --session <id>  # the commands one Pi agent ran, and its final message
```

OpenRouter refuses a request when the credit left can't cover every request in flight. With little credit, set **Session concurrency** to 1 in StuntHog's settings.

`stunthog.ts` options:

| Option      | Default                                                          | What it sets                                                    |
| ----------- | ---------------------------------------------------------------- | --------------------------------------------------------------- |
| `--url`     | `STUNTHOG_URL` or `http://127.0.0.1:3100`                        | The StuntHog server                                             |
| `--only`    | Every eval                                                       | Eval keys, separated by commas                                  |
| `--models`  | Claude Sonnet 5.5, Claude Opus 5.5, GPT Sol and Gemini Pro on Pi | `<harness>:<model>` pairs                                       |
| `--judge`   | `pi:anthropic/claude-opus-5.5`                                   | The judge's harness and model                                   |
| `--count`   | `1`                                                              | Sessions per model                                              |
| `--run`     | Off                                                              | Starts each eval after saving it                                |
| `--variant` | None                                                             | Runs a local hog build from `variant.sh` instead of the release |

Running the script again updates the evals in place. StuntHog keeps earlier revisions and their sessions.

### Compare a change

`variant.sh` builds hog from this checkout into a variant, with its own Dockerfiles. Eval titles get the variant name, so its sessions sit next to the release's.

```sh
git checkout my-change
hog/evals/variant.sh my-change                 # SKILLS_ZIP=<path> also serves a local context-mill bundle
bun hog/evals/stunthog.ts --variant my-change --run --only handoff,basic
git checkout master && hog/evals/variant.sh base
bun hog/evals/stunthog.ts --variant base --run --only handoff,basic
```

Compare more than one session per model: the same build scores a criterion or two apart between runs.

## The evals

| Key           | Scenario  | Checks                                                                                              |
| ------------- | --------- | --------------------------------------------------------------------------------------------------- |
| `handoff`     | `never`   | The agent relays the link, code, region note and sign-up note, then stops                           |
| `discovery`   | `never`   | The agent finds hog on the machine when the prompt doesn't name it                                  |
| `basic`       | `approve` | A full install: skill reads, token from hog, signup event, review, wrap-up                          |
| `replay`      | `approve` | Session replay: product choice, the right skill, recording turned on                                |
| `flags`       | `approve` | A flag for the button label: product choice, skill, flag in PostHog, code with a safe default       |
| `experiments` | `approve` | An A/B test on the button: experiment skill, experiment in PostHog, variant code and a metric event |
| `surveys`     | `approve` | A post-signup survey: survey skill, survey in PostHog, targeted at new signups                      |
| `flask`       | `approve` | A Flask server app: one server client, the signup event with the user's id, posthog-js in the pages |
| `eu`          | `approve` | `--region eu` before any link, EU hosts in `posthog.json` and posthog-js                            |
| `denied`      | `denied`  | The agent reports the rejection and doesn't work around it                                          |
| `quiet`       | `quiet`   | The agent says no events arrived yet and how to send some                                           |
| `skills`      | `never`   | `hog skills search` and `add` pick a replay setup skill                                             |

Every setup eval also checks that the agent went through `hog setup` and never tried to approve the login itself, fetch the approval page, or make up keys.

`fixtures/storefront` is the app most sessions get: a small Next.js store with a signup form. The `flask` eval gets `fixtures/flask-shop`, the same store as a Flask app with Jinja templates.

## Add a scenario or an eval

- A new fake-user behavior goes in `SCENARIOS` in `mock/addon.py` and the port list in `mock/start.sh`.
- A new eval goes in `EVALS` in `stunthog.ts`. Write each criterion so a judge can check it from the transcript alone.
- A new endpoint hog calls shows up in the log as `unmocked` or `api_generic`. Add a handler in `mock/addon.py` when the answer matters.
