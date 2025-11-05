# SCIM Implementation Spike Summary

## Overview

SCIM 2.0 (System for Cross-domain Identity Management) enables automated user provisioning and deprovisioning from identity providers (Okta, Azure AD, etc.) into PostHog.

## Architecture

### Domain-Level Tenancy

- SCIM configuration stored on `OrganizationDomain` model (follows SAML pattern)
- Each domain has unique bearer token for authentication
- URL structure: `/scim/v2/{domain_id}/Users`
- Ensures tenant isolation matching existing SAML implementation

### User Provisioning Strategy

- **No passwords**: SCIM-created users have `password=None`
- **SAML authentication required**: Users must use SAML to login
- **Email auto-verified**: `is_email_verified=True`
- **Default membership level**: `OrganizationMembership.Level.MEMBER`
- **Existing user handling**: If user exists, add to org and update attributes

### Group Mapping

- SCIM Groups → PostHog RBAC Roles
- **Upsert by name**: Groups auto-create roles if they don't exist
- **Name matching**: Case-sensitive role name matching
- **Membership sync**: PATCH operations sync role memberships

### User Deactivation

- DELETE or `active=false` removes `OrganizationMembership` only
- User remains active in other organizations
- Does NOT set `User.is_active=False` globally

## Files

### Models

- `posthog/models/organization_domain.py` - Added `scim_enabled`, `scim_bearer_token` fields

### Core SCIM Implementation (`ee/api/scim/`)

- `auth.py` - Bearer token authentication
- `user.py` - SCIM User adapter (maps to PostHog User model)
- `group.py` - SCIM Group adapter (maps to PostHog Role model)
- `views.py` - SCIM 2.0 endpoints
- `utils.py` - Helper functions for token management

### API Management

- `posthog/api/organization_domain.py`
    - serializer/viewset exposing SCIM config via domain PATCH (`scim_enabled`)
    - action endpoint for bearer rotation (`POST /scim/token`)

### Configuration

- `ee/urls.py` - SCIM URL routing
- `ee/settings.py` - SCIM service provider config
- `pyproject.toml` - Added `django-scim2==0.19.0` dependency

### Testing

- `ee/api/scim/test/test_scim_api.py` - Comprehensive SCIM endpoint tests

## API Endpoints

### SCIM Endpoints (IdP Integration)

```text
GET    /scim/v2/{domain_id}/Users              # List users
POST   /scim/v2/{domain_id}/Users              # Create user
GET    /scim/v2/{domain_id}/Users/{id}         # Get user
PUT    /scim/v2/{domain_id}/Users/{id}         # Replace user
PATCH  /scim/v2/{domain_id}/Users/{id}         # Update user
DELETE /scim/v2/{domain_id}/Users/{id}         # Deactivate user

GET    /scim/v2/{domain_id}/Groups             # List groups
POST   /scim/v2/{domain_id}/Groups             # Create group
GET    /scim/v2/{domain_id}/Groups/{id}        # Get group
PUT    /scim/v2/{domain_id}/Groups/{id}        # Replace group
PATCH  /scim/v2/{domain_id}/Groups/{id}        # Update group
DELETE /scim/v2/{domain_id}/Groups/{id}        # Delete group

GET    /scim/v2/{domain_id}/ServiceProviderConfig  # Provider capabilities
GET    /scim/v2/{domain_id}/ResourceTypes          # Resource types
GET    /scim/v2/{domain_id}/Schemas                # SCIM schemas
```

### Management Endpoints (PostHog UI)

```text
PATCH /api/organizations/{org_id}/domains/{domain_id} (scim_enabled)   # Enable/disable SCIM
POST  /api/organizations/{org_id}/domains/{domain_id}/scim/token       # Regenerate bearer token
```

SCIM configuration (enabled state, base URL) is returned directly on the `OrganizationDomain` resource.

#### Example: enable SCIM (mirrors JIT provisioning toggle)

PATCH: `https://app.posthog.com/api/organizations/<org_id>/domains/<domain_id>/`

```json
{
  "scim_enabled": true
}
```

Successful response includes the one-time bearer token and SCIM base URL:

```json
{
  "id": "<domain_id>",
  "domain": "example.com",
  "scim_enabled": true,
  "scim_base_url": "https://app.posthog.com/scim/v2/<domain_id>",
  "scim_bearer_token": "<plain_token_once>",
  ...
}
```

#### Example: disable SCIM

PATCH: `https://app.posthog.com/api/organizations/<org_id>/domains/<domain_id>/`

```json
{
  "scim_enabled": false
}
```

Response mirrors JIT disabling: `scim_enabled` becomes `false` and no token is returned.

## Authentication Flow

1. IdP makes request to SCIM endpoint with `Authorization: Bearer {token}`
2. `SCIMBearerTokenAuthentication` extracts domain_id from URL
3. Retrieves `OrganizationDomain` and validates token (hashed comparison)
4. Returns domain as `request.auth` for tenant scoping
5. Views filter all queries by `organization_domain.organization`

## PATCH Operations Support

Both Users and Groups support standard SCIM PATCH operations via the `django-scim2` library.

### User PATCH Operations

**Replace** - Update user attributes:

```json
{
  "Operations": [
    { "op": "replace", "path": "name.givenName", "value": "Alice" },
    { "op": "replace", "path": "name.familyName", "value": "Smith" },
    { "op": "replace", "path": "active", "value": false }
  ]
}
```

**Add** - Add/set attributes (reactivate user if adding `active=true`):

```json
{
  "Operations": [{ "op": "add", "path": "name.givenName", "value": "Bob" }]
}
```

**Remove** - Clear attributes (deactivates user if removing `active`):

```json
{
  "Operations": [
    { "op": "remove", "path": "name.givenName" },
    { "op": "remove", "path": "active" }
  ]
}
```

### Group PATCH Operations

**Replace** - Update group name or sync members:

```json
{
  "Operations": [
    { "op": "replace", "path": "displayName", "value": "Engineering" },
    { "op": "replace", "path": "members", "value": [{ "value": "user-uuid-1" }, { "value": "user-uuid-2" }] }
  ]
}
```

**Add** - Add members without removing existing ones:

```json
{
  "Operations": [{ "op": "add", "path": "members", "value": [{ "value": "user-uuid-3" }] }]
}
```

**Remove** - Remove specific members or all members:

```json
{
  "Operations": [{ "op": "remove", "path": "members[value eq \"user-uuid\"]" }]
}
```

## License Feature Availability

SCIM is a licensed feature that requires `AvailableFeature.SCIM` to be enabled for the organization.

### How It Works

- The SCIM endpoints check if the organization has the SCIM feature enabled
- License checks happen in the authentication layer via `SCIMBearerTokenAuthentication`
- If the feature is not available, requests return `403 Forbidden`

### Testing Locally

Enabling SCIM via Django shell:

```python
from posthog.constants import AvailableFeature
from posthog.models.organization_domain import OrganizationDomain

domain = OrganizationDomain.objects.get(domain="posthog.com")
org = domain.organization

# Add SCIM to available features
org.available_product_features.append({
    "key": AvailableFeature.SCIM,
    "name": "SCIM"
})
org.save()
```

Get the bearer token and base URL from Settings → Authentication domains or via Django shell:

```python
token = enable_scim_for_domain(domain)
print(f"Bearer Token: {token}")

scim_url = get_scim_base_url(domain)
print(f"SCIM Base URL: {scim_url}")
```

## User Lifecycle Examples

### Create User (New)

```json
POST /scim/v2/{domain_id}/Users
{
  "userName": "alice@example.com",
  "name": {"givenName": "Alice", "familyName": "Smith"},
  "active": true
}
```

**Result**:

- Creates `User` with `password=None`, `is_email_verified=True`
- Creates `OrganizationMembership` with `level=MEMBER`
- User must authenticate via SAML

### Create User (Existing)

If user exists in another org:

- Adds `OrganizationMembership` to this org
- Updates `first_name`, `last_name` if provided
- No duplicate user created

### Update User

```json
PATCH /scim/v2/{domain_id}/Users/{id}
{
  "Operations": [
    {"op": "replace", "value": {"name": {"givenName": "Alicia"}}}
  ]
}
```

**Result**: Updates `user.first_name = "Alicia"`

### Deactivate User

```json
PATCH /scim/v2/{domain_id}/Users/{id}
{
  "Operations": [
    {"op": "replace", "value": {"active": false}}
  ]
}
```

**Result**: Deletes `OrganizationMembership` (user stays active elsewhere)

## Group Management Examples

### Create Group

```json
POST /scim/v2/{domain_id}/Groups
{
  "displayName": "Engineering",
  "members": [{"value": "user-id"}]
}
```

**Result**:

- Upserts `Role` with `name="Engineering"`
- Creates `RoleMembership` for specified users

### Update Group Members

```json
PATCH /scim/v2/{domain_id}/Groups/{id}
{
  "Operations": [
    {"op": "replace", "value": {"members": [{"value": "user-id-1"}, {"value": "user-id-2"}]}}
  ]
}
```

**Result**: Syncs `RoleMembership` to match provided list

## SCIM + JIT Provisioning

When both SCIM and JIT (Just-In-Time) provisioning are enabled for a domain:

1. **User joins via SAML**: User can self-join the organization through SAML authentication and automatically gets `MEMBER` access level
2. **SCIM synchronization**: IdP's SCIM sync will then update:
   - User's first name and last name
   - User's role/group memberships (via Group operations)
   - Any other SCIM-managed attributes

This allows for a hybrid approach where users can access the organization immediately via SAML, and SCIM handles ongoing attribute and role synchronization from the IdP.

**Note**: When SCIM provisions a user that already exists (from JIT), it adds them to the organization if they're not already a member, then updates their attributes.

## Security Considerations

1. **Token Storage**: Bearer tokens hashed with Django password hashers
2. **Tenant Isolation**: Domain ID in URL enforces scoping
3. **No Password Leakage**: SCIM users never have passwords
4. **SAML Required**: Must configure SAML before SCIM is useful
5. **License Check**: `AvailableFeature.SCIM` required for access

## Testing

Run tests:

```bash
pytest ee/api/scim/test/test_scim_api.py
pytest ee/api/scim/test/test_users_api.py
pytest ee/api/scim/test/test_groups_api.py
```

## IdP Configuration Guide

### OneLogin

1. Go to Applications → Applications → Add App → Search for **"SCIM Provisioner with SAML (SCIM v2 full SAML)"**
2. SCIM Base URL: For cloud, use `https://app.posthog.com/scim/v2/{domain_id}`. For local testing, use your ngrok URL, e.g. `https://<ngrok-subdomain>.ngrok.io/scim/v2/{domain_id}`. The `{domain_id}` can be copied directly from the SCIM configuration screen in PostHog.
3. Bearer Token: Paste the generated Bearer Token from PostHog. It's only shown on first enable or when regenerating.
4. Enable provisioning in the Configuration and Provisioning tabs (otherwise, OneLogin won't push any updates).
5. In "Rules", you can sync Role membership by: - Mapping OneLogin roles or groups directly to existing groups in PostHog (by matching names), or - Mapping OneLogin roles/groups that will be upserted in PostHog as needed
   In most cases you'll want the second - it pushes OneLogin roles to PostHog.
   To configure this, set the condition to: "Match `any` of the following conditions" and select the roles you want to provision by choosing "Roles include <ONELOGIN-ROLE-NAME>".
   Then set the actions to "Map from OneLogin" and "For each `roles` with a value that matches `.*`"
6. Add users to the App if they weren't added automatically
7. Save, and test by adding or updating users/roles

**Note**: The custom parameters (email, first_name, last_name) configured in step 5 are **NOT** sent via SCIM. They are only used in SAML assertions for authentication. SCIM operations use the standard SCIM 2.0 attribute names:

- `userName` for identifier
- `emails[].value` array for email addresses
- `name.givenName` for first name
- `name.familyName` for last name

## Frontend UI

The SCIM configuration interface is available in the PostHog settings:

**Location**: Settings → Organization → Verified Domains → [Domain] → More → Configure SCIM

**Features**:

- 'Configure SCIM' button is only visible if `AvailableFeature.SCIM` is enabled
- Enable/disable SCIM toggle
- Display SCIM base URL (with copy button)
- Display bearer token (one-time, shown only after enable/regenerate)
- Regenerate token button with confirmation

**Implementation**:

- Modal component: `frontend/src/scenes/settings/organization/VerifiedDomains/ConfigureSCIMModal.tsx`
- Logic: `frontend/src/scenes/settings/organization/VerifiedDomains/verifiedDomainsLogic.ts`

## Remaining Nice-to-Haves

1. **Pagination**:
   - Support `startIndex` and `count` params

2. **Bulk Operations**:
   - `POST /Bulk` endpoint

3. **Activity Logging**:
   - Log SCIM user create/update/delete events
   - Track which IdP made changes

4. **Rate Limiting**:
   - Add per-domain rate limits
   - Protect against aggressive IdP sync
