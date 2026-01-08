# Surveys

## Setting up your environment

1. Follow the [local development guide](https://posthog.com/handbook/engineering/developing-locally) to set up your environment.
2. Run `python manage.py generate_random_surveys` to generate a survey with responses for testing. By default, this creates 1 survey with 50 responses covering all actionable question types (open, rating, single choice with open-ended, multiple choice with open-ended).

   Available parameters:
   - `count` - Number of surveys to generate (default: 1)
   - `--responses` - Number of responses per survey (default: 50)
   - `--team-id` - Team ID to create surveys for (default: first team)
   - `--days-back` - Spread responses over the last N days (default: 30)

## How to test changes

### PostHog App Changes (Backend/Frontend)

- Run the app locally following the [local development guide](https://posthog.com/handbook/engineering/developing-locally)
- Write tests for logic changes, especially in `surveyLogic.tsx` or `surveysLogic.tsx`

### JS SDK Changes

Most survey logic lives in the [PostHog JS SDK](https://github.com/PostHog/posthog-js/). To test changes:

First, build the package with hot-reload:

```bash
cd posthog-js # root of repo
pnpm package:watch # generates tarballs with hot-reload
```

This watches for changes and rebuilds automatically. Now pick your testing environment:

#### Option 1: NextJS playground (recommended)

The playground is the fastest way to iterate on SDK changes.

1. Import the surveys module in `playground/nextjs/src/posthog.ts`:

```typescript
import 'posthog-js/dist/surveys'
```

2. (Optional) Disable consent checks to simplify testing:

```typescript
export const configForConsent = (): Partial<PostHogConfig> => {
  const consentGiven = cookieConsentGiven()
  return {
    disable_surveys: false, // force surveys on
    autocapture: consentGiven === 'granted',
    disable_session_recording: consentGiven !== 'granted',
  }
}
```

3. Update `playground/nextjs/package.json` to use your local build:

**Manually:**

```json
{
  "dependencies": {
    "posthog-js": "file:/path/to/posthog-js/target/posthog-js.tgz"
  }
}
```

**Or via script** (run from posthog-js root):

```bash
TGZ_PATH="$(pwd)/target/posthog-js.tgz"
sed -i '' "s|\"posthog-js\": \".*\"|\"posthog-js\": \"file:$TGZ_PATH\"|" playground/nextjs/package.json
```

4. Clean & run:

```bash
cd playground/nextjs
rm -rf node_modules .next && pnpm install && pnpm dev
```

Changes are picked up automatically via `package:watch`.

#### Option 2: Main PostHog repo

1. Update `frontend/package.json` to use your local build:

**Manually:**

```json
{
  "dependencies": {
    "posthog-js": "file:/path/to/posthog-js/target/posthog-js.tgz"
  }
}
```

**Or via script:**

```bash
# Adjust these paths to match your setup
POSTHOG_JS_DIR=~/src/posthog-js
DOTCOM_DIR=~/src/dotcom

TGZ_PATH="$POSTHOG_JS_DIR/target/posthog-js.tgz"
sed -i '' "s|\"posthog-js\": \".*\"|\"posthog-js\": \"file:$TGZ_PATH\"|" "$DOTCOM_DIR/frontend/package.json"
cd "$DOTCOM_DIR" && pnpm install
# restart the frontend
```

#### External (hosted) surveys

**Quick context:**

- The external survey template is in the main repo at `posthog/templates/surveys/public_survey.html`
- This template is served from the backend at `posthog/api/survey.py`
  - Look for function: `public_survey_page(request, survey_id: str)`

**How to test**

1. Build the JS SDK, either with `pnpm package:watch` or just `pnpm build`

2. Copy the dist file to the main repo:

```bash
cp /path/to/posthog-js/packages/browser/dist/array.full.js /path/to/posthog/frontend/dist/
```

3. Update `posthog/templates/surveys/public_survey.html` to load your local SDK file:

```html
<!-- keep this project config script as-is -->
<!-- PostHog JavaScript -->
<script nonce="{{ request.csp_nonce }}">
  // Project config from Django and helper functions
  const survey = {{ survey_data | safe }};
  const projectConfig = {{ project_config_json | safe }};
  ...
</script>

<!-- add this just above the existing CDN loader -->
<script src="/static/array.full.js" nonce="{{ request.csp_nonce }}"></script>

<script nonce="{{ request.csp_nonce }}">
  // Load PostHog from CDN
  !function (t, e) ...; // remove/comment this line!
</script>
```

4. Start the backend services however you normally do, e.g. `hogli start`

5. You should be able to see a survey with your local SDK changes on port `8010` or `8000`, e.g.:

```text
http://localhost:8000/external_surveys/019aea73-43d7-0000-9638-02f9368f964b?q0=5&auto_submit=true
```

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

- Maintain consistent URLs between sessions
- Avoid CORS issues by keeping the same origin

One caveat: **reserved ngrok domains are only available for paid ngrok users.**

### Testing survey usage_report

The function [get_teams_with_survey_responses_count_in_period](https://github.com/PostHog/posthog/blob/master/posthog/tasks/usage_report.py#L790) is used to get the number of survey responses in a given period. We use that for billing.

Here's how to run it in the Django shell:

```python
# In python manage.py shell
from posthog.tasks.usage_report import get_teams_with_survey_responses_count_in_period
from datetime import datetime, timedelta, UTC

# Define the period for the last 60 days
now = datetime.now(tz=UTC)
start_time = now - timedelta(days=60)
end_time = now

results = get_teams_with_survey_responses_count_in_period(start_time, end_time)
print(results)
```

## Debugging

### posthog-js logs

We [added some logging on the JS SDK](https://github.com/PostHog/posthog-js/pull/1663) to help debug issues with surveys.

However, those logs are only enabled when posthog-js (v1.117.0 and higher) is set with debug=true.

For customer issues, if you need it, you can add the query parameter `__posthog_debug=true` to force the JS SDK to be loaded with debugging mode.

Example: `https://posthog.com/?__posthog_debug=true`

If you ever need more logs, please create a PR and add them.

### Cache Consistency Issues

When surveys are not loaded in the SDKs (/decide returns surveys: false), it could be caused by cache inconsistencies in the team settings.

#### What is `surveys_opt_in` and why it matters

The `surveys_opt_in` field on the Team model is a critical flag that determines whether surveys functionality is enabled for a team. During the `/decide` API call (which the SDK makes on initialization), this value is checked to determine if survey functionality should be loaded.

How it works:

- The `/decide` endpoint includes `"surveys": surveys_opt_in` in its response
- The RemoteConfig system also includes this value in its cached configuration
- When the JS SDK initializes, it checks this value to determine if it should load survey functionality
- If `surveys_opt_in` is `false` in the cache but `true` in the database (or vice versa), surveys may not work correctly

If cache inconsistencies occur, customers may report that their surveys aren't appearing despite being properly configured, or surveys may continue to appear after being disabled.

When to use:

- When the /decide API response shows surveys_opt_in as false, but surveys are configured and should be active in the app.

```python
# In Django shell (python manage.py shell_plus)
from posthog.models.surveys.debug import (
    check_team_cache_consistency,
    fix_team_cache_consistency,
    find_teams_with_cache_inconsistencies,
    fix_all_teams_cache_consistency
)

# Check single team
check_team_cache_consistency("team_id_or_token")

# Fix single team
fix_team_cache_consistency("team_id_or_token")

# Find all teams with issues (only active survey teams)
find_teams_with_cache_inconsistencies()

# Fix all teams with issues
fix_all_teams_cache_consistency()
```

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
