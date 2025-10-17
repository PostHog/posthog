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

- `posthog/api/organization_domain_scim.py` - Mixin for SCIM config endpoints

### Configuration

- `ee/urls.py` - SCIM URL routing
- `ee/settings.py` - SCIM service provider config
- `pyproject.toml` - Added `django-scim2==0.19.0` dependency

### Testing

- `ee/api/scim/test/test_scim_api.py` - Comprehensive SCIM endpoint tests

### Migration

- `posthog/migrations/0868_add_scim_fields_to_organization_domain.py` - Database migration

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
GET  /api/organizations/{org_id}/domains/{domain_id}/scim              # Get config
POST /api/organizations/{org_id}/domains/{domain_id}/scim              # Enable SCIM
POST /api/organizations/{org_id}/domains/{domain_id}/scim/regenerate   # Regenerate token
POST /api/organizations/{org_id}/domains/{domain_id}/scim/disable      # Disable SCIM
```

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

To enable SCIM feature for local development via Django shell:

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

### Enabling SCIM via Django Shell

To enable SCIM and get the bearer token via Django shell:

```python
from posthog.models.organization_domain import OrganizationDomain
from ee.api.scim.utils import enable_scim_for_domain, get_scim_base_url

domain = OrganizationDomain.objects.get(domain="posthog.com")

token = enable_scim_for_domain(domain)
print(f"Bearer Token: {token}")

scim_url = get_scim_base_url(domain)
print(f"SCIM Base URL: {scim_url}")

# Now you can use this to make requests via Postman
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
  "members": [{"value": "user-uuid"}]
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
    {"op": "replace", "value": {"members": [{"value": "user-uuid-1"}, {"value": "user-uuid-2"}]}}
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
pytest ee/api/scim/test/test_scim_api.py -v
```

Test coverage:

- ✅ User CRUD operations
- ✅ Group CRUD operations
- ✅ Token authentication (valid/invalid/missing)
- ✅ Existing user handling
- ✅ Multi-org scenarios
- ✅ Member deactivation
- ✅ Group membership sync
- ✅ Service provider config
- ✅ PATCH operations (replace, add, remove)

## IdP Configuration Guide

### Okta

1. Applications → Create SCIM Integration
2. SCIM Base URL: `https://app.posthog.com/scim/v2/{domain_id}`
3. Auth: OAuth Bearer Token (paste generated token)
4. Supported features: Push New Users, Push Profile Updates, Push Groups
5. Attribute mappings:
    - userName → email
    - name.givenName → firstName
    - name.familyName → lastName

### Azure AD

1. Enterprise Apps → Provision User Accounts
2. Tenant URL: `https://app.posthog.com/scim/v2/{domain_id}`
3. Secret Token: (paste generated token)
4. Mappings:
    - userPrincipalName → userName
    - givenName → name.givenName
    - surname → name.familyName

## Frontend UI

The SCIM configuration interface is available in the PostHog settings:

**Location**: Settings → Organization → Verified Domains → [Domain] → More → Configure SCIM

**Features**:

- Enable/disable SCIM toggle with confirmation dialogs
- Display SCIM base URL (with copy button)
- Display bearer token (one-time, shown only after enable/regenerate)
- Regenerate token button with warning confirmation
- Feature flag gating - button only visible if `AvailableFeature.SCIM` is enabled

**Implementation**:

- Modal component: `frontend/src/scenes/settings/organization/VerifiedDomains/ConfigureSCIMModal.tsx`
- Logic: `frontend/src/scenes/settings/organization/VerifiedDomains/verifiedDomainsLogic.ts`

## Remaining Nice-to-Haves:

1. **Activity Logging**:
    - Log SCIM user create/update/delete events
    - Track which IdP made changes

2. **Rate Limiting**:
    - Add per-domain rate limits
    - Protect against aggressive IdP sync

3. **Filtering Support**:
    - `GET /Users?filter=userName eq "user@example.com"`

4. **Pagination**:
    - Support `startIndex` and `count` params

5. **Bulk Operations**:
    - `POST /Bulk` endpoint
