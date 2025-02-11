# Surveys

## How to test changes

### PostHog App Changes (Backend/Frontend)

-   Run the app locally following the [local development guide](https://posthog.com/handbook/engineering/developing-locally)
-   Write tests for logic changes, especially in `surveyLogic.tsx` or `surveysLogic.tsx`

### JS SDK Changes

Most survey logic lives in the [PostHog JS SDK](https://github.com/PostHog/posthog-js/). To test changes:

1. Use the [NextJS playground](https://github.com/PostHog/posthog-js/tree/main/playground/nextjs) (recommended)

2. To test SDK changes in the main PostHog app:
    - Update `package.json` to use your local SDK:
    ```json
    "posthog-js": "file:../posthog-js"
    ```
    - Restart the frontend process after running `bin/start`

Because of RemoteConfig, you'll likely need to run the main PostHog app with your local posthog-js files to see the changes.

### Mobile Device Testing

To test on mobile devices, use [ngrok](https://ngrok.com/) to expose localhost:

1. Sample `ngrok.yml`:

```yaml
version: '3'
agent:
    authtoken: YOUR_AUTH_TOKEN
tunnels:
    web:
        proto: http
        addr: 8010
        host_header: rewrite
        subdomain: posthog-web-test
    app:
        proto: http
        addr: 3000
        subdomain: posthog-app-test
```

2. Add this `.env` configuration:

```env
# Core URLs
SITE_URL=https://posthog-web-test.ngrok.io
JS_URL=https://posthog-web-test.ngrok.io

# CORS and security
CORS_ALLOW_ALL_ORIGINS=true
CORS_ALLOW_CREDENTIALS=True
ALLOWED_HOSTS=*,localhost,localhost:8010,127.0.0.1,127.0.0.1:8010,posthog-web-test
DISABLE_SECURE_SSL_REDIRECT=True
SECURE_COOKIES=False

# Proxy settings
IS_BEHIND_PROXY=true
USE_X_FORWARDED_HOST=true
USE_X_FORWARDED_PORT=true
TRUST_ALL_PROXIES=true

# Debug settings
DEBUG=true
DJANGO_DEBUG=true
SERVE_STATIC=true
```

Using reserved ngrok domains is recommended to:

-   Maintain consistent URLs between sessions
-   Avoid CORS issues by keeping the same origin

One caveat: **reserved ngrok domains are only available for paid ngrok users.**

## Debugging

### posthog-js logs

We [added some logging on the JS SDK](https://github.com/PostHog/posthog-js/pull/1663) to help debug issues with surveys.

However, those logs are only enabled when posthog-js (v1.117.0 and higher) is set with debug=true.

For customer issues, if you need it, you can add the query parameter `__posthog_debug=true` to force the JS SDK to be loaded with debugging mode.

Example: `https://posthog.com/?__posthog_debug=true`

If you ever need more logs, please create a PR and add them.

### Database debugging

Access the database via Django admin, you can do so by opening:

https://{eu|us}.posthog.com/admin/posthog/survey/{survey_id}/change/

Access the database via Metabase, you can do so by opening:

- [EU](https://metabase.prod-eu.posthog.dev/browse/databases/34-posthog-postgres-prod-eu) - Posthog Survey
- [US](https://metabase.prod-us.posthog.dev/browse/databases/34-posthog-postgres-prod-us-aurora) - Posthog Survey

You can execute SQL queries directly in Metabase.

```sql
select * from posthog_survey
 where id = '{survey_id}'
```

Access postgres directly, check the [runbook](http://runbooks/postgres#accessing-postgres) (internal PostHog link).
