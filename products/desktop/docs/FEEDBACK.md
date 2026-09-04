# Desktop feedback

People can select **Send feedback…** from the account menu, use the command menu, or press `Cmd+Shift+F` on macOS and `Ctrl+Shift+F` on other systems.

The form sends a response to the Desktop feedback survey. Each response includes the current view and related task or folder ID when available. The existing app version, user, project, organization, and session context are also attached by PostHog analytics.

The form captures a bounded screenshot before it opens. The person can review and remove the screenshot. Recent app logs are attached only after the person selects that option and reviews the exact text. Screenshots and logs can contain code, file paths, tokens, or customer data, so they must never be sent without this review step.

Survey responses can be enabled as a Product analytics feedback source in Signals. This keeps feedback review and self-driving follow-up on the same structured source.
