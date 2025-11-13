---
title: OAuth Development Guide
sidebar: Handbook
showTitle: true
---

# OAuth Development Guide

This guide helps developers set up and test PostHog's OAuth apps locally.

## Quick Start

### 1. Set Up Your Environment

First, generate demo data which includes a test OAuth application:

```bash
python manage.py generate_demo_data
```

### 2. Configure RSA Keys

OAuth uses RS256 for signing JWT tokens. Copy the RSA private key from the example file:

```bash
# Copy the OIDC_RSA_PRIVATE_KEY from .env.example to your .env file
grep OIDC_RSA_PRIVATE_KEY .env.example >> .env
```

Or generate a new key pair:

```bash
# Generate a new RSA private key
openssl genrsa 2048 | openssl pkcs8 -topk8 -nocrypt -outform PEM | \
  awk 'NF {sub(/\r/, ""); printf "%s\\n",$0;}'

# Add to .env as OIDC_RSA_PRIVATE_KEY="<generated_key>"
```

### 3. Access the Demo Application

After running `generate_demo_data`, a test OAuth application is created with these credentials:

- **Client ID**: `DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ`
- **Client Secret**: `GQItUP4GqE6t5kjcWIRfWO9c0GXPCY8QDV4eszH4PnxXwCVxIMVSil4Agit7yay249jasnzHEkkVqHnFMxI1YTXSrh8Bj1sl1IDfNi1S95sv208NOc0eoUBP3TdA7vf0`
- **Redirect URIs**: `http://localhost:3000/callback`, `https://example.com/callback`, `http://localhost:8237/callback`, `http://localhost:8239/callback`

You can view and test the OAuth flow from Django admin:

1. Navigate to `http://localhost:8010/admin/posthog/oauthapplication/`
2. Click "View on site" to see an example authorization URL with PKCE parameters

## Creating an OAuth Application

### Via Django Admin

1. Navigate to `http://localhost:8010/admin/posthog/oauthapplication/`
2. Click "Add OAuth Application"
3. Configure the application fields (see below)

### Application Fields

#### Basic Information

**Name** (required)
- Display name for the application
- Shown to users during authorization
- Example: "PostHog Mobile App", "Analytics Dashboard"

**Client ID** (auto-generated)
- Unique identifier for your application
- Automatically generated but can be customized
- Used in authorization requests
- Example: `DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ`

**Client Secret** (auto-generated)
- Confidential credential for the application
- Only shown once during creation
- Gets hashed after saving
- Only used by confidential clients
- ⚠️ **Copy this before you save the application - you cannot view it again after creation**

**Client Type** (required)
- `Confidential`: For server-side applications that can securely store secrets
- `Public`: For client-side apps (mobile, SPA) that cannot securely store secrets

See [Client Types](#client-types) section for detailed explanation.

#### Authorization Settings

**Authorization Grant Type** (required, fixed)
- Only `Authorization code` is supported

**Redirect URIs** (required)
- Whitespace-separated list of valid redirect URIs
- PostHog will only redirect to these URIs after authorization
- **HTTPS required** for non-localhost URIs
- **HTTP allowed** only for localhost/loopback addresses (127.0.0.1)
- No fragments (#) allowed
- Examples:
  ```
  https://app.example.com/oauth/callback
  http://localhost:3000/callback
  http://127.0.0.1:8080/auth
  ```

**Algorithm** (required, fixed)
- Only `RS256` (RSA with SHA-256) is supported
- Used for signing ID tokens
- More secure than symmetric algorithms (HS256)
- Cannot be changed

#### Ownership

**User**
- The PostHog user who created the application
- Not used for access control
- Helps track who created the app

**Organization**
- The organization that owns this application
- In the future, we will allow organizations to manage their apps in their settings
- If organization is deleted, app becomes orphaned but remains active.

## Client Types

### Confidential Clients

**Use for**: Server-side applications, backend services, traditional web apps

**Characteristics**:
- Can securely store the client secret
- Runs in a trusted environment (your servers)
- Must authenticate with both client_id and client_secret when exchanging authorization code for tokens

**Examples**:
- Django/Rails/Express web applications
- Backend services
- Server-to-server integrations

**Security**: Higher - the secret never leaves your secure server environment

### Public Clients

**Use for**: Single-page apps (SPAs), mobile apps, desktop apps

**Characteristics**:
- Cannot securely store secrets (code is distributed to users)
- Relies on PKCE for security instead of client secret
- Only needs client_id for token exchange

**Examples**:
- React/Vue/Angular applications
- iOS/Android mobile apps
- Electron desktop applications

## OAuth Flow

### Standard Authorization Code Flow with PKCE

1. **Generate PKCE parameters** (client-side):
   ```python
   import secrets
   import hashlib
   import base64

   # Generate random code_verifier
   code_verifier = secrets.token_urlsafe(32)

   # Create code_challenge
   digest = hashlib.sha256(code_verifier.encode('utf-8')).digest()
   code_challenge = base64.urlsafe_b64encode(digest).decode('utf-8').replace('=', '')
   ```

2. **Redirect user to authorization URL**:
   ```
   GET /oauth/authorize/
     ?response_type=code
     &client_id=DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ
     &redirect_uri=http://localhost:3000/callback
     &scope=openid experiment:read query:read
     &code_challenge=<generated_code_challenge>
     &code_challenge_method=S256
     &state=<random_state_value>
   ```

3. **User authorizes** the application and selects access level

4. **Receive authorization code** at redirect_uri:
   ```
   http://localhost:3000/callback?code=<authorization_code>&state=<state_value>
   ```

5. **Exchange code for tokens**:
   ```bash
   POST /oauth/token/
   Content-Type: application/x-www-form-urlencoded

   grant_type=authorization_code
   &code=<authorization_code>
   &redirect_uri=http://localhost:3000/callback
   &client_id=DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ
   &client_secret=<client_secret>  # Only for confidential clients
   &code_verifier=<original_code_verifier>
   ```

6. **Response includes**:
   ```json
   {
     "access_token": "...",
     "token_type": "Bearer",
     "expires_in": 36000,
     "refresh_token": "...",
     "id_token": "...",
     "scope": "openid experiment:read query:read",
     "scoped_teams": [1, 2],
     "scoped_organizations": ["org-uuid"]
   }
   ```

## Available Scopes

OAuth supports all the same scopes as Personal API Keys. Each scope has a `read` and/or `write` action (e.g., `experiment:read`, `experiment:write`).

For a complete list of available scopes, see [frontend/src/lib/scopes.tsx](https://github.com/PostHog/posthog/blob/master/frontend/src/lib/scopes.tsx#L15).

### OpenID Connect Scopes

Standard OpenID Connect scopes are also supported:

- `openid` - Required for OpenID Connect (provides ID token with user identity claims)
- `profile` - Access to user profile information (name, username, etc.)
- `email` - Access to user email address

## Access Levels

When authorizing an application, users can scope access to:

1. **All**: Access to all organizations and teams the user is a member of
2. **Organization**: Access limited to specific organizations
3. **Team**: Access limited to specific teams/projects

This is configured during the authorization step, not in the application settings.

If you would like to force the user to pick a single team or an organization you can use the `required_access_level=project` or `required_access_level=organization` query parameter in the authorization url.

## Testing Your OAuth Application

### Using the Admin Interface

1. Go to `http://localhost:8010/admin/posthog/oauthapplication/`
2. Click your application
3. Click "View on site" - this generates a test authorization URL with:
   - Proper PKCE code_challenge (using code_verifier="test")
   - First configured redirect_uri
   - Example scopes

### Manual Testing

Use the demo application credentials to test the full flow:

```python
# Example using requests library
import requests
import secrets
import hashlib
import base64

# Step 1: Generate PKCE
code_verifier = "test"  # Use something random in production
digest = hashlib.sha256(code_verifier.encode('utf-8')).digest()
code_challenge = base64.urlsafe_b64encode(digest).decode('utf-8').replace('=', '')

# Step 2: Build authorization URL
auth_url = (
    "http://localhost:8010/oauth/authorize/"
    "?response_type=code"
    "&client_id=DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ"
    "&redirect_uri=http://localhost:3000/callback"
    "&scope=openid+experiment:read"
    f"&code_challenge={code_challenge}"
    "&code_challenge_method=S256"
    "&state=random_state_123"
)

print(f"Visit: {auth_url}")

# Step 3: After authorization, extract code from redirect
# Step 4: Exchange for tokens
token_response = requests.post(
    "http://localhost:8010/oauth/token/",
    data={
        "grant_type": "authorization_code",
        "code": "<code_from_redirect>",
        "redirect_uri": "http://localhost:3000/callback",
        "client_id": "DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ",
        "client_secret": "GQItUP4GqE6t5kjcWIRfWO9c0GXPCY8QDV4eszH4PnxXwCVxIMVSil4Agit7yay249jasnzHEkkVqHnFMxI1YTXSrh8Bj1sl1IDfNi1S95sv208NOc0eoUBP3TdA7vf0",
        "code_verifier": code_verifier,
    }
)

tokens = token_response.json()
print(tokens)
```

## Endpoints

- **Authorization**: `/oauth/authorize/`
- **Token Exchange**: `/oauth/token/`
- **Token Revocation**: `/oauth/revoke_token/`
- **User Info**: `/oauth/userinfo/`
- **JWKS (Public Keys)**: `/oauth/.well-known/jwks.json`
- **OpenID Configuration**: `/oauth/.well-known/openid-configuration/`

## Troubleshooting

### "Invalid client_id"
- Check the client_id matches exactly
- Verify the application exists in `https://localhost:8010/admin/posthog/oauthapplication/`

### "Redirect URI mismatch"
- Ensure redirect_uri in request matches one configured in application, make sure you included the path and not just the base url
- Check for trailing slashes
- Verify HTTP vs HTTPS

### "Invalid code_verifier"
- The code_verifier used in token exchange must match the one used to generate code_challenge
- Ensure code_challenge was generated correctly using SHA256, you should send the hashed version as the code_challenge in the authorize request, and the original as the code_verifier in the token request

### "Invalid client_secret"
- For confidential clients, ensure you saved the secret during creation, after creation you will see a hashed version in Django admin which is not your client secret
- Secrets cannot be retrieved after creation - you'll need to create a new application

## Additional Resources

- OAuth 2.0 RFC: https://tools.ietf.org/html/rfc6749
- OpenID Connect Core: https://openid.net/specs/openid-connect-core-1_0.html
- PKCE RFC: https://tools.ietf.org/html/rfc7636
