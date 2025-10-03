# SCIM Implementation Spike Summary

## Overview

This spike implements SCIM 2.0 (System for Cross-domain Identity Management) for PostHog, enabling automated user provisioning and deprovisioning from identity providers (Okta, Azure AD, etc.).

## Architecture Decisions

### 1. **Domain-Level Tenancy** (Follows SAML Pattern)
- SCIM configuration stored on `OrganizationDomain` model
- Each domain has unique bearer token for authentication
- URL structure: `/scim/v2/{domain_id}/Users`
- Ensures tenant isolation matching existing SAML implementation

### 2. **User Provisioning Strategy**
- **No passwords**: SCIM-created users have `password=None`
- **SAML authentication required**: Users must use SAML to login
- **Email auto-verified**: `is_email_verified=True`
- **Default membership level**: `OrganizationMembership.Level.MEMBER`
- **Existing user handling**: If user exists, add to org and update attributes

### 3. **Group Mapping**
- SCIM Groups → PostHog RBAC Roles
- **Upsert by name**: Groups auto-create roles if they don't exist
- **Name matching**: Case-sensitive role name matching
- **Membership sync**: PATCH operations sync role memberships

### 4. **User Deactivation**
- DELETE or `active=false` removes `OrganizationMembership` only
- User remains active in other organizations
- Does NOT set `User.is_active=False` globally

## Files Created

### Models
- `posthog/models/organization_domain.py` - Added `scim_enabled`, `scim_bearer_token` fields

### Core SCIM Implementation (`ee/api/scim/`)
- `auth.py` - Bearer token authentication
- `user.py` - SCIM User adapter (maps to PostHog User model)
- `group.py` - SCIM Group adapter (maps to PostHog Role model)
- `views.py` - SCIM 2.0 endpoints
- `utils.py` - Helper functions for token management
- `README.md` - Implementation documentation

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
```
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
```
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

## Security Considerations

1. **Token Storage**: Bearer tokens hashed with Django password hashers
2. **Tenant Isolation**: Domain ID in URL enforces scoping
3. **No Password Leakage**: SCIM users never have passwords
4. **SAML Required**: Must configure SAML before SCIM is useful
5. **License Check**: Skipped in spike (add `AvailableFeature.SCIM` later)

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

## Next Steps (Not in Spike)

### Required for Production
1. **Frontend UI**:
   - Add SCIM config to VerifiedDomains settings page
   - Show SCIM base URL and token (one-time display)
   - Regenerate token button
   - Enable/disable toggle

2. **License Check**:
   - Add `AvailableFeature.SCIM` constant
   - Validate in SCIM views
   - Billing integration

3. **Activity Logging**:
   - Log SCIM user create/update/delete events
   - Track which IdP made changes

4. **Rate Limiting**:
   - Add per-domain rate limits
   - Protect against aggressive IdP sync

### Nice to Have
5. **Filtering Support**:
   - `GET /Users?filter=userName eq "user@example.com"`

6. **Pagination**:
   - Support `startIndex` and `count` params

7. **Bulk Operations**:
   - `POST /Bulk` endpoint

8. **Webhooks**:
   - Notify on SCIM events

9. **Validation Rules**:
   - Prevent SCIM + JIT provisioning conflicts
   - Warn if SAML not configured

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

## Deployment Checklist

- [ ] Run migration: `python manage.py migrate`
- [ ] Install dependency: `django-scim2==0.19.0`
- [ ] Test SCIM endpoints with Postman/curl
- [ ] Configure test IdP (Okta/Azure AD)
- [ ] Verify user provisioning works
- [ ] Verify group sync works
- [ ] Add frontend UI for SCIM config
- [ ] Add license checks
- [ ] Add activity logging
- [ ] Update docs

## Questions Answered

1. ✅ **Domain-level or Org-level?** Domain-level (follows SAML)
2. ✅ **Password for SCIM users?** No password (SAML only)
3. ✅ **Group mapping?** Upsert roles by name
4. ✅ **Default membership level?** MEMBER
5. ✅ **User deactivation?** Remove OrganizationMembership only
6. ✅ **Existing user conflict?** Add to org, update attributes
7. ✅ **Attribute mapping?** userName→email, givenName→first_name, familyName→last_name
8. ✅ **License check?** Skipped in spike (add later)
