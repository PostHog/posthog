# OAuth API

## End-to-End Testing

### Prerequisites

1. Start required services:

   ```bash
   docker compose -f docker-compose.dev.yml up -d db redis7
   ```

2. Run migrations and start the server:

   ```bash
   python manage.py migrate
   python manage.py runserver 8000
   ```

3. Ensure you have a user account and are logged in via browser.

### Manual E2E Test Flow

1. **Get an OAuth app's client_id and generate PKCE values:**

   ```bash
   python manage.py shell << 'EOF'
   import hashlib, base64, os
   from posthog.models import OAuthApplication

   app = OAuthApplication.objects.filter(name__icontains="your-app-name").first()
   print(f"CLIENT_ID={app.client_id}")
   print(f"REDIRECT_URIS={app.redirect_uris}")

   # Generate PKCE
   code_verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b'=').decode('utf-8')
   code_challenge = base64.urlsafe_b64encode(
       hashlib.sha256(code_verifier.encode('utf-8')).digest()
   ).rstrip(b'=').decode('utf-8')
   print(f"CODE_VERIFIER={code_verifier}")
   print(f"CODE_CHALLENGE={code_challenge}")
   EOF
   ```

2. **Navigate to the authorization URL in a browser (must be logged in):**

   ```text
   http://localhost:8000/oauth/authorize/?client_id=<CLIENT_ID>&redirect_uri=<REDIRECT_URI>&response_type=code&scope=openid&code_challenge=<CODE_CHALLENGE>&code_challenge_method=S256
   ```

3. **Click "Authorize"** - you'll be redirected to the callback URL with a `code` parameter.

4. **Exchange the code for a token:**

   ```bash
   curl -s -X POST http://localhost:8000/oauth/token/ \
     -H "Content-Type: application/json" \
     -d '{
       "grant_type": "authorization_code",
       "code": "<CODE_FROM_REDIRECT>",
       "client_id": "<CLIENT_ID>",
       "redirect_uri": "<REDIRECT_URI>",
       "code_verifier": "<CODE_VERIFIER>"
     }' | python3 -m json.tool
   ```

5. **Verify the response** contains `access_token`, `refresh_token`, `expires_in`, etc.

### Testing Token Introspection

```bash
curl -s -X POST http://localhost:8000/oauth/introspect/ \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"token": "<ACCESS_TOKEN>"}' | python3 -m json.tool
```

### Unit Tests

Run OAuth-specific tests:

```bash
pytest posthog/api/oauth/test_views.py -v
```

Run a specific test:

```bash
pytest posthog/api/oauth/test_views.py::TestOAuthAPI::test_name -v
```
