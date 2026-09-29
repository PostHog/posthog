# mobilehog

A stripped-back Expo app over PostHog cloud tasks, built for a local stack.

## Local stack

In the posthog repo, once:

```bash
echo 'ALLOW_DEV_API_KEY_REVEAL=1' >> .env
echo 'SANDBOX_PROVIDER=docker' >> .env
flox activate -- bash -c "python manage.py setup_local_api_key"
```

Then restart the stack. The login screen posts email and password to `/api/login/`, reads the seeded local dev personal API key, and uses it as a bearer token from then on.

## Run

```bash
cd products/desktop
pnpm install
pnpm --filter @posthog/mobilehog ios     # first build
pnpm --filter @posthog/mobilehog start   # afterwards
```

The host lives in `src/config.ts`. Use your LAN IP instead of `localhost` on a real phone.
