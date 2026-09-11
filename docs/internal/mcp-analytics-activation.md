# MCP analytics setup measurement

The product empty state offers Wizard, an installation prompt for a coding agent, and manual documentation.
Wizard targets the selected project with `--project-id`.
The agent prompt includes the selected project ID and backend URL, but no credentials.
It links to the existing Markdown installation guide so the app does not depend on a new documentation URL being deployed first.

## Events

The shared `productSetupStatusLogic` emits these events.
Existing click event names remain unchanged.

| Event                                           | Meaning                                                                                                             |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `product empty state shown`                     | The setup surface rendered for the selected project. Filter `mode = needs-setup` for the initial setup denominator. |
| `product empty state wizard command copied`     | The command reached the clipboard. This does not prove the installer started.                                       |
| `product empty state agent instructions opened` | The agent prompt dialog opened.                                                                                     |
| `product empty state agent prompt copied`       | The installation prompt reached the clipboard. This does not prove the agent ran.                                   |
| `product empty state manual setup clicked`      | The manual setup documentation opened.                                                                              |
| `product empty state wizard session observed`   | A current, project-matching `mcp-analytics` Wizard session appeared or changed phase in the inline progress view.   |
| `product empty state data detected`             | The product's detection logic reported `has-data` after a setup exposure or interaction in this browser.            |

Each setup event includes `product_key`, `project_id`, `project_uuid`, `setup_attempt_id`, `initial_setup_route`, and `setup_route`.
Shown and interaction events also include `mode`.
Route values are `wizard`, `agent`, or `manual`; they are null until a command/prompt is copied or the manual link is clicked.
Opening the agent dialog does not select the agent route.
The initial route remains fixed while the current route changes as someone tries another path.

`setup_attempt_id` identifies the first setup journey in one browser for one product and project.
It persists across navigation and reloads in local storage.
It is not a project-wide or cross-device identifier.
The data-detected event is emitted at most once per stored attempt.
MCP signal queries discard successes and failures when the selected project UUID changes while the query is in flight.
Clearing browser storage starts a new attempt, so deduplicate analysis by project, not by attempt count.
Forced `?empty_state` previews, Storybook previews, and impersonated sessions do not emit the new setup funnel events.

Wizard observations also include `wizard_session_id` and `wizard_phase`.
The session ID is the session API's ID, not the CLI's process-level `run_id` or the cloud run's `wizard_run_id`.
The authenticated session belongs to the selected project, which connects observed progress to the UI cohort without adding an unsupported CLI flag.
Deduplicate Wizard observations by project, session ID, and phase.
They can repeat on remount, and a completed session can be observed without its running phase being seen.

## Funnel and outcomes

Use the earliest eligible `product empty state shown` event per project as the cohort entry.
Filter `product_key = mcp_analytics` and `mode = needs-setup`, exclude internal/test projects, and allow a full seven-day observation window.
Use the existing instance and project UUID groups (`$group_1`, `$group_2`) as the project key; numeric IDs alone collide across regions.

Measure these separately:

1. Setup shown -> any setup route chosen.
2. Setup shown -> `product empty state data detected` within seven days.
3. Setup shown -> the existing stored product activation timestamp within seven days.

Keep route choice as a diagnostic breakdown.
It is not a randomized comparison: people who choose different installers can differ before installation.
An experiment should assign variants at the project level and compare all eligible exposed projects in each assigned variant.
This change does not create or start an experiment.

The existing activation definition remains unchanged: MCP tool-call data plus an MCP analytics view.
Use the stored product-intent activation timestamp for that metric; the activation event alone misses immediate activations.

The data-detected event is a browser observation, not an ingestion timestamp or proof of SDK installation on a particular server.
It can miss projects whose data arrives while no setup detection is mounted.
MCP analytics detection currently accepts any `$mcp_tool_call` in the project, including hosted PostHog MCP traffic.
To measure installation of an owned server, independently verify the server identity on the ingested call.
Do not report this frontend proxy as that stronger metric.

The app cannot observe an external agent starting or completing installation from a copied prompt alone.
Keep those stages unknown until there is evidence.
The prompt instructs the agent to verify a real tool-call event and to report pending verification when it cannot access PostHog.

## Verification flow

The existing setup detector keeps polling for MCP data.
The inline Wizard view tracks the `mcp-analytics` workflow and shows its existing progress, failure, and report surfaces.
A completed Wizard run is not evidence of a captured tool call.
After setup, invoke an existing safe tool and inspect its event in the selected project's MCP analytics activity view.
When data arrives, the existing empty-state gate reveals the product's activity/first-look surface.
Stateless MCP clients may omit initialization, so `$mcp_initialize` is not required for completion.
