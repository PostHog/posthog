# Self-driving features: internal testing

Self-driving features reuse inbox reports as durable feature records. The implementation and ownership contract is described in [the product architecture](../../products/signals/backend/features.md).

## Rollout

Keep `self-driving-features` off by default. Configure it as an organization-targeted flag and enable only the internal test organization. The same key gates the Features tab, the feature API, discovery activity startup, and owner scout loading. Both inbox layouts support it.

Deploy the Signals migrations, including the merged migration history and the discovery checkpoint column. Regenerate API clients with `hogli build:openapi` after changing endpoints. The feature API uses `task:read` for lists and readiness, and `task:write` for discovery, planning, and implementation actions.

Disabling the flag prevents new launches. Cancel already running Tasks separately if a test needs to stop immediately. No feature flag can undo a pushed commit or an opened pull request.

## Walkthrough

Use a connected repository intended for internal testing. Work through each step and inspect the report feed before proceeding.

1. With the flag off, verify the Features tab is absent and feature endpoints return 404 for an authenticated user.
2. Enable the flag for the test organization. Open Features in both inbox layouts, then open a feature and return to the list.
3. Start a narrowly focused discovery. Inspect its task, recorded repository evidence, staged reports, questions, and owner recommendations. Discovery must create no pull requests or owner scouts.
4. Open a discovered feature's Planning tab. Verify opening it creates no task. Start planning explicitly and check the selected repository and existing report context.
5. Answer a suggested question with a custom response beginning with one of its option labels. Move focus away and back; the draft must survive. Repeat with an optionless question.
6. Resolve all agent questions and confirm the title, summary, repository, owners, priority, and owner playbook. The backend readiness endpoint must report no missing requirements.
7. Finish planning. Confirm one owner scout named with the full report UUID, one implementation task, and the managed lifecycle. Repeating the action must not create another initial implementation task.
8. Inspect the implementation task's acting user and internal mode. Try starting another pass while it is active; it must be refused. After completion, review the PR and recorded commits before launching another pass.
9. Revisit planning on the managed feature. Its owner and lifecycle must remain intact. Continue a completed planning conversation and verify the continuation still cannot open a pull request.
10. Run the owner scout and inspect measurements, linked reports, new questions, and proposed work. A question must block implementation until answered. Check missing project access prevents launch.
11. Disable the flag and confirm new feature actions and owner launches stop.

Test pagination with enough staged results to require another page; managed and planning features must remain visible in their independent list. Automatic discovery retries should retain completed documents and remain visibly running until success or terminal failure.

## Existing branch data

Earlier versions named owner scouts with the first eight UUID characters. Multiple features created together could share one scout. Re-submit the existing feature's Finish planning action as the intended execution user to create its full-UUID owner and disable the legacy config. This repairs ownership without starting a second initial implementation pass. Repeat for each managed feature; repairing just one cannot recover the others' independent owners.

Readiness now validates repository and owner values and requires all agent questions to be answered. Resolve outstanding requirements before repairing an old feature. Existing disabled full-UUID owner configs retain their enabled state; re-enable them through the scout controls when intended.

## Validation boundaries

Unit and API tests cover gating, lifecycle, pagination, readiness, execution identity, duplicate launch protection, and discovery retries. A live sandbox run is still needed to validate GitHub access, agent behavior, PR creation, and PostHog measurements. Merge approval remains a separate human decision.
