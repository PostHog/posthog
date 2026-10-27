# Bets

- Follow repository and frontend instructions. Bets lives under `products/bets`, behind the `bets` release flag.
- Reuse PostHog scouts, reports, tasks, insights, experiments, flags, activity logs, and notifications through their public facades. Bets owns intent, coordination, and budget allocation.
- Use Quill and the Today design conventions. Keep implementation concepts out of the primary UI.
- Store money as integer cents. Budget operations are append-only and idempotent. Closing work never refunds settled spending.
- Verify changes in the running app, including narrow layouts and failure states. Keep screenshots under the ignored `verification/` directory.
