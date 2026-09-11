# Replay Vision scanner feedback

Scanner feedback uses the existing PostHog JavaScript SDK and survey renderer.
It does not change scanner confirmation, permissions, billing, or API behavior.

## User experience

- After a successful disable or delete in the web app, show an optional survey in the corner of the screen.
- Ask for one reason. Offer an optional text question next. Store the reason even if the person closes the second question.
- Show each survey once. Suppress all scanner feedback surveys for 30 days after any survey was shown, including one that was dismissed.
- After a successful enable of an existing scanner, offer a **Share your goal** button in the success message. Do not open a survey automatically.
- Offer that button at most once per person per browser session. Respect survey eligibility again when the person selects it.
- Do not show a survey after a failed operation or when the SDK is unavailable. Do not wait for the SDK to load and then show a delayed prompt.
- Do not request feedback for scanner creation, duplication, API calls, or automated changes.

The SDK handles survey eligibility, the close button, response capture, and the waiting period.
The integration passes `ignoreConditions: false` on every display call.
Feedback failures must not reverse a successful scanner operation or show an operation error.

## Survey definitions and rollout

The definitions are API surveys. They cannot open automatically on a page visit.
`SCANNER_FEEDBACK_SURVEY_IDS` in `scannerFeedback.ts` links each action to its definition.
Keep the surveys as drafts until the integration is deployed and checked.

Before launch, check each definition:

- Disable reasons: cost, irrelevant findings, inaccurate findings, insufficient useful results, a break, no further need, or another reason.
- Delete reasons: the same quality and cost categories, plus replacement and test cleanup.
- Enable goals: find bugs, find user problems, check a change, monitor a flow, understand use, or another goal.
- Use a once-only schedule. Set each waiting period to 30 days after any survey.
- Enable partial responses and make the text question optional.

Use survey audience controls for a small initial rollout.
Launch the disable survey first, then the delete survey after checking dismissals and responses.
End or archive a survey to stop new requests without a code deployment.
Do not convert these definitions to automatically triggered popover surveys.

## Measurement and privacy

Use the standard `survey shown`, `survey sent`, and `survey dismissed` events.
Each event carries `scanner_id`, `scanner_action`, `scanner_feedback_source`, and `project_id`.
Do not attach scanner names, prompts, findings, recordings, or customer details.
Ask people not to include private information in text responses.

Compare reasons separately for disable and delete.
Track shown-to-response and shown-to-dismissal rates, and check scanner operation errors during rollout.
Use the existing scanner lifecycle events as the count of completed operations.
Survey responses are a selected sample, not the reason for every disable or delete.
