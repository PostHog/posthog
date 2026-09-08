# Claude subscription billing for Desktop cloud tasks

Desktop can use a user's Claude subscription for cloud model usage.
Sandbox compute continues to use PostHog credits.

1. Deploy the tasks backend and publish the sandbox agent build with `--claudeSubscription` support.
2. Enable `posthog-code-claude-own-subscription-cloud` for the intended users.
3. In Desktop, open **Settings > Harness > Claude subscription**. Under **Cloud tasks**, select **Create token**.
4. Complete the steps in the app terminal. Copy the token, close the terminal, then paste and save the token.
5. Enable **Cloud tasks** and select a Claude model.
6. Keep Desktop open when starting or continuing the task so it can supply the credential.

To renew a token, select **Replace token**. The saved token remains available until the new token is saved.
**Cancel** keeps the saved token.

An unavailable flag, missing credential, or incompatible sandbox fails the requested subscription run without switching to PostHog model billing.
Continuations inherit the billing choice unless explicitly changed.
If a run is still stopping, wait for it to stop before sending another message.
Subscription runs skip prewarmed sessions.
They use direct event ingest so the credential request can reach Desktop before the agent session is ready.

For the transport and storage boundaries, see [the credential relay design](../../products/desktop/docs/CLOUD-MCP-RELAY.md#claude-subscription-credentials).
