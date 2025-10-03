# SCIM 2.0 Implementation for PostHog

This directory contains the SCIM 2.0 (System for Cross-domain Identity Management) implementation for PostHog, enabling automated user provisioning and group management from identity providers.

## Architecture

The SCIM implementation follows PostHog's existing multitenant SAML architecture:

- **Per-Domain Tenancy**: Each `OrganizationDomain` has its own SCIM configuration and bearer token
- **SAML Integration**: SCIM provisioned users authenticate via SAML (no passwords)
- **RBAC Mapping**: SCIM Groups map to PostHog RBAC Roles

## Components

### Models (`posthog/models/organization_domain.py`)

Extended `OrganizationDomain` with:
- `scim_enabled`: Boolean flag to enable/disable SCIM
- `scim_bearer_token`: Hashed bearer token for authentication
- `has_scim`: Property to check if SCIM is properly configured

### Authentication (`auth.py`)

- `SCIMBearerTokenAuthentication`: DRF authentication class
  - Extracts domain ID from URL path
  - Validates bearer token against hashed value
  - Returns `OrganizationDomain` as auth object for tenant isolation

### Adapters

#### User Adapter (`user.py`)
- Maps SCIM User schema to PostHog `User` model
- **Create**: Creates user with no password, marks as email verified
- **Update**: Updates user attributes
- **Delete**: Removes `OrganizationMembership` (user remains active in other orgs)
- **Upsert**: If user exists, adds them to organization

#### Group Adapter (`group.py`)
- Maps SCIM Group schema to PostHog RBAC `Role` model
- **Create**: Upserts role by name
- **Update**: Manages role membership via `RoleMembership`
- **Delete**: Deletes the role

### Views (`views.py`)

SCIM 2.0 compliant endpoints:

**Users:**
- `GET /scim/v2/{domain_id}/Users` - List users
- `POST /scim/v2/{domain_id}/Users` - Create user
- `GET /scim/v2/{domain_id}/Users/{id}` - Get user
- `PUT /scim/v2/{domain_id}/Users/{id}` - Replace user
- `PATCH /scim/v2/{domain_id}/Users/{id}` - Update user
- `DELETE /scim/v2/{domain_id}/Users/{id}` - Deactivate user

**Groups:**
- `GET /scim/v2/{domain_id}/Groups` - List groups
- `POST /scim/v2/{domain_id}/Groups` - Create group
- `GET /scim/v2/{domain_id}/Groups/{id}` - Get group
- `PUT /scim/v2/{domain_id}/Groups/{id}` - Replace group
- `PATCH /scim/v2/{domain_id}/Groups/{id}` - Update group
- `DELETE /scim/v2/{domain_id}/Groups/{id}` - Delete group

**Discovery:**
- `GET /scim/v2/{domain_id}/ServiceProviderConfig` - Provider capabilities
- `GET /scim/v2/{domain_id}/ResourceTypes` - Available resource types
- `GET /scim/v2/{domain_id}/Schemas` - SCIM schemas

## Usage

### Enabling SCIM

```python
from ee.api.scim.utils import enable_scim_for_domain
from posthog.models.organization_domain import OrganizationDomain

domain = OrganizationDomain.objects.get(id="...")
token = enable_scim_for_domain(domain)  # Returns plain token (show once!)

# Get SCIM base URL
from ee.api.scim.utils import get_scim_base_url
scim_url = get_scim_base_url(domain)  # https://app.posthog.com/scim/v2/{domain_id}
```

### IdP Configuration

Configure your IdP (Okta, Azure AD, etc.) with:

1. **SCIM Base URL**: `https://app.posthog.com/scim/v2/{domain_id}`
2. **Authentication**: Bearer Token (from enable step above)
3. **User Attributes**:
   - userName → email
   - name.givenName → first_name
   - name.familyName → last_name
4. **Group Mapping**: IdP groups → PostHog Roles (by name)

### User Lifecycle

1. **Create**: IdP sends `POST /Users`
   - Creates `User` with no password
   - Creates `OrganizationMembership` with MEMBER level
   - User authenticates via SAML

2. **Update**: IdP sends `PATCH /Users/{id}`
   - Updates user attributes
   - Can modify group memberships

3. **Deactivate**: IdP sends `PATCH /Users/{id}` with `active=false` or `DELETE`
   - Removes `OrganizationMembership`
   - User remains active in other organizations

### Group Management

1. **Create Group**: IdP sends `POST /Groups`
   - Upserts `Role` by name matching

2. **Add Members**: IdP sends `PATCH /Groups/{id}`
   - Creates `RoleMembership` entries
   - Removes members not in updated list

3. **Delete Group**: IdP sends `DELETE /Groups/{id}`
   - Deletes the `Role`

## Behavior Details

### User Creation
- **New User**: Creates user, adds to org
- **Existing User**: Adds to org, updates attributes
- **Password**: Always `None` (SAML authentication required)
- **Email Verification**: Auto-verified (`is_email_verified=True`)
- **Default Role**: `OrganizationMembership.Level.MEMBER`

### User Deactivation
- Removes `OrganizationMembership` only
- User remains active for other organizations
- Does NOT set `User.is_active=False`

### Group Mapping
- SCIM Groups → PostHog Roles (1:1)
- Group name must match Role name (case-sensitive)
- Auto-creates roles if they don't exist
- Members managed via `RoleMembership`

### Tenant Isolation
- Each domain has unique bearer token
- URL includes `domain_id` for scoping
- All queries filtered by `organization`

## Testing

Run tests:
```bash
pytest ee/api/scim/test/test_scim_api.py
```

Key test scenarios:
- User CRUD operations
- Group CRUD operations
- Member management
- Token authentication
- Existing user handling
- Multi-org scenarios

## Security

- **Bearer Token**: Hashed with Django's password hashers
- **Tenant Isolation**: Domain ID in URL path enforces scoping
- **No Password Storage**: SCIM users have `password=None`
- **SAML Required**: Users must authenticate via SAML

## Limitations

- No bulk operations support
- No filtering support
- No sorting support
- Groups must match existing Role names exactly
- User creation requires SAML to be configured

## Migration Path

1. Run migration: `python manage.py migrate`
2. Add SCIM config to frontend (VerifiedDomains settings)
3. Enable SCIM per domain via admin/API
4. Configure IdP with SCIM endpoint and token
5. Test user provisioning
6. Enable SSO enforcement if desired

## Future Enhancements

- [ ] Add filtering support (e.g., `filter=userName eq "user@example.com"`)
- [ ] Add pagination for large result sets
- [ ] Support bulk operations
- [ ] Auto-create default team for SCIM users
- [ ] Activity logging for SCIM operations
- [ ] Rate limiting per domain
- [ ] SCIM event webhooks
