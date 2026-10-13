# Create surveys through MCP

PostHog's MCP tools can create, update, launch, and stop surveys without opening the survey editor. Ask your agent to use the `creating-surveys` skill when available.

## Create a draft

Describe the feedback you need, who should receive the survey, and how it should appear. For example: "Create a draft NPS survey with an optional follow-up question for people using the settings page."

The agent uses `survey-create` to save the draft and `survey-get` to read it back for review. Omitting `start_date` keeps a new survey in draft.

Choose the delivery type that matches your goal:

| Type              | Use                                                                    |
| ----------------- | ---------------------------------------------------------------------- |
| `popover`         | An in-app survey displayed by a supported PostHog SDK                  |
| `widget`          | An always-available feedback button, with SDK and widget configuration |
| `external_survey` | A hosted form with a shareable public link                             |
| `api`             | A custom form rendered and instrumented in your application            |

Creating an `api` survey saves its definition. Your application still needs to display it and capture survey events.

## Review targeting and appearance

Use `conditions` for display rules such as URL and event conditions. Use `targeting_flag_filters` for person, group, or cohort properties. Cohorts containing behavioral filters cannot be used directly for survey targeting. A static snapshot is an alternative, but its membership will not update automatically.

Hosted forms do not use in-app targeting. Their public form URL is different from the management URL returned in `_posthogUrl`.

Appearance customization is optional. Removing PostHog branding with `whiteLabel: true` requires the organization's white-labelling entitlement. Popup delays must be non-negative. An agent should explain unsupported settings rather than silently changing your branding or widening the audience.

## Launch and check results

Review the saved questions, audience, schedule, and response limit before launch. Ask the agent to launch with `survey-launch` when ready. If you already requested immediate launch, the agent can continue after checking the configuration and delivery requirements.

In-app surveys require surveys to be enabled and supported by the application's SDK. Configuring an event trigger does not add event capture code to your application. An archived survey must be unarchived before launch, and a past end date must be cleared or extended when reopening it.

Use `survey-stats` or `surveys-responses-list` to check activity. Use `survey-stop` to stop collection. When updating questions, keep existing question IDs so answers remain associated with the right questions.

## Survey identifiers

Pass the returned survey `id` as the `id` argument to subsequent survey tools. Question IDs and feature flag IDs are different identifiers.

Creation is not idempotent. After a timeout, inspect existing surveys before retrying to avoid creating a duplicate.
