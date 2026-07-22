/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - core
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Manage CIMD verification tokens for an organization.
 *
 * A partner embeds the plaintext token in their CIMD metadata document as
 * `verification_token` inside the `com.posthog` object (the legacy top-level
 * `posthog_verification_token` field still works as a fallback). When PostHog fetches
 * the metadata, matching the token links the partner app to this organization and
 * grants a higher default rate limit for account provisioning.
 *
 * The plaintext value is only available on creation; we store a hash.
 */
export const cimdVerificationTokensCreateBodyLabelMax = 40

export const CimdVerificationTokensCreateBody = /* @__PURE__ */ zod.object({
    label: zod.string().max(cimdVerificationTokensCreateBodyLabelMax),
})

export const domainsCreateBodyDomainMax = 128

export const domainsCreateBodySsoEnforcementMax = 28

export const DomainsCreateBody = /* @__PURE__ */ zod.object({
    domain: zod.string().max(domainsCreateBodyDomainMax),
    jit_provisioning_enabled: zod.boolean().optional(),
    sso_enforcement: zod.string().max(domainsCreateBodySsoEnforcementMax).optional(),
    identity_provider_config: zod
        .uuid()
        .nullish()
        .describe(
            'Linked IdP configuration (SAML\/SCIM\/XAA) that backs this domain. Must belong to the same organization.'
        ),
})

export const domainsUpdateBodyDomainMax = 128

export const domainsUpdateBodySsoEnforcementMax = 28

export const DomainsUpdateBody = /* @__PURE__ */ zod.object({
    domain: zod.string().max(domainsUpdateBodyDomainMax),
    jit_provisioning_enabled: zod.boolean().optional(),
    sso_enforcement: zod.string().max(domainsUpdateBodySsoEnforcementMax).optional(),
    identity_provider_config: zod
        .uuid()
        .nullish()
        .describe(
            'Linked IdP configuration (SAML\/SCIM\/XAA) that backs this domain. Must belong to the same organization.'
        ),
})

export const domainsPartialUpdateBodyDomainMax = 128

export const domainsPartialUpdateBodySsoEnforcementMax = 28

export const DomainsPartialUpdateBody = /* @__PURE__ */ zod.object({
    domain: zod.string().max(domainsPartialUpdateBodyDomainMax).optional(),
    jit_provisioning_enabled: zod.boolean().optional(),
    sso_enforcement: zod.string().max(domainsPartialUpdateBodySsoEnforcementMax).optional(),
    identity_provider_config: zod
        .uuid()
        .nullish()
        .describe(
            'Linked IdP configuration (SAML\/SCIM\/XAA) that backs this domain. Must belong to the same organization.'
        ),
})

export const domainsVerifyCreateBodyDomainMax = 128

export const domainsVerifyCreateBodySsoEnforcementMax = 28

export const DomainsVerifyCreateBody = /* @__PURE__ */ zod.object({
    domain: zod.string().max(domainsVerifyCreateBodyDomainMax),
    jit_provisioning_enabled: zod.boolean().optional(),
    sso_enforcement: zod.string().max(domainsVerifyCreateBodySsoEnforcementMax).optional(),
    identity_provider_config: zod
        .uuid()
        .nullish()
        .describe(
            'Linked IdP configuration (SAML\/SCIM\/XAA) that backs this domain. Must belong to the same organization.'
        ),
})

export const identityProviderConfigsCreateBodyNameMax = 255

export const identityProviderConfigsCreateBodySamlEntityIdMax = 512

export const identityProviderConfigsCreateBodySamlAcsUrlMax = 512

export const identityProviderConfigsCreateBodyIdJagIssuerUrlMax = 512

export const identityProviderConfigsCreateBodyIdJagJwksUrlMax = 512

export const identityProviderConfigsCreateBodyIdJagAllowedClientsItemMax = 256

export const IdentityProviderConfigsCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(identityProviderConfigsCreateBodyNameMax)
        .optional()
        .describe("Display name for this IdP configuration (e.g. 'Okta production')."),
    saml_entity_id: zod
        .string()
        .max(identityProviderConfigsCreateBodySamlEntityIdMax)
        .nullish()
        .describe('SAML IdP entity ID (issuer).'),
    saml_acs_url: zod
        .string()
        .max(identityProviderConfigsCreateBodySamlAcsUrlMax)
        .nullish()
        .describe('SAML single sign-on (ACS) URL the IdP redirects to.'),
    saml_x509_cert: zod.string().nullish().describe('SAML IdP X.509 signing certificate (PEM).'),
    scim_enabled: zod
        .boolean()
        .optional()
        .describe(
            'Whether SCIM provisioning is enabled. Setting this true generates a bearer token (returned once); setting it false clears the token.'
        ),
    id_jag_issuer_url: zod
        .string()
        .max(identityProviderConfigsCreateBodyIdJagIssuerUrlMax)
        .nullish()
        .describe('Trusted IdP issuer URL for ID-JAG (XAA). Required to enable ID-JAG.'),
    id_jag_jwks_url: zod
        .string()
        .max(identityProviderConfigsCreateBodyIdJagJwksUrlMax)
        .nullish()
        .describe('Override JWKS URL. Defaults to OIDC discovery on the issuer URL.'),
    id_jag_allowed_clients: zod
        .array(zod.string().max(identityProviderConfigsCreateBodyIdJagAllowedClientsItemMax))
        .optional()
        .describe('Allowed ID-JAG client IDs. Empty list allows any client_id.'),
})

export const identityProviderConfigsUpdateBodyNameMax = 255

export const identityProviderConfigsUpdateBodySamlEntityIdMax = 512

export const identityProviderConfigsUpdateBodySamlAcsUrlMax = 512

export const identityProviderConfigsUpdateBodyIdJagIssuerUrlMax = 512

export const identityProviderConfigsUpdateBodyIdJagJwksUrlMax = 512

export const identityProviderConfigsUpdateBodyIdJagAllowedClientsItemMax = 256

export const IdentityProviderConfigsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(identityProviderConfigsUpdateBodyNameMax)
        .optional()
        .describe("Display name for this IdP configuration (e.g. 'Okta production')."),
    saml_entity_id: zod
        .string()
        .max(identityProviderConfigsUpdateBodySamlEntityIdMax)
        .nullish()
        .describe('SAML IdP entity ID (issuer).'),
    saml_acs_url: zod
        .string()
        .max(identityProviderConfigsUpdateBodySamlAcsUrlMax)
        .nullish()
        .describe('SAML single sign-on (ACS) URL the IdP redirects to.'),
    saml_x509_cert: zod.string().nullish().describe('SAML IdP X.509 signing certificate (PEM).'),
    scim_enabled: zod
        .boolean()
        .optional()
        .describe(
            'Whether SCIM provisioning is enabled. Setting this true generates a bearer token (returned once); setting it false clears the token.'
        ),
    id_jag_issuer_url: zod
        .string()
        .max(identityProviderConfigsUpdateBodyIdJagIssuerUrlMax)
        .nullish()
        .describe('Trusted IdP issuer URL for ID-JAG (XAA). Required to enable ID-JAG.'),
    id_jag_jwks_url: zod
        .string()
        .max(identityProviderConfigsUpdateBodyIdJagJwksUrlMax)
        .nullish()
        .describe('Override JWKS URL. Defaults to OIDC discovery on the issuer URL.'),
    id_jag_allowed_clients: zod
        .array(zod.string().max(identityProviderConfigsUpdateBodyIdJagAllowedClientsItemMax))
        .optional()
        .describe('Allowed ID-JAG client IDs. Empty list allows any client_id.'),
})

export const identityProviderConfigsPartialUpdateBodyNameMax = 255

export const identityProviderConfigsPartialUpdateBodySamlEntityIdMax = 512

export const identityProviderConfigsPartialUpdateBodySamlAcsUrlMax = 512

export const identityProviderConfigsPartialUpdateBodyIdJagIssuerUrlMax = 512

export const identityProviderConfigsPartialUpdateBodyIdJagJwksUrlMax = 512

export const identityProviderConfigsPartialUpdateBodyIdJagAllowedClientsItemMax = 256

export const IdentityProviderConfigsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(identityProviderConfigsPartialUpdateBodyNameMax)
        .optional()
        .describe("Display name for this IdP configuration (e.g. 'Okta production')."),
    saml_entity_id: zod
        .string()
        .max(identityProviderConfigsPartialUpdateBodySamlEntityIdMax)
        .nullish()
        .describe('SAML IdP entity ID (issuer).'),
    saml_acs_url: zod
        .string()
        .max(identityProviderConfigsPartialUpdateBodySamlAcsUrlMax)
        .nullish()
        .describe('SAML single sign-on (ACS) URL the IdP redirects to.'),
    saml_x509_cert: zod.string().nullish().describe('SAML IdP X.509 signing certificate (PEM).'),
    scim_enabled: zod
        .boolean()
        .optional()
        .describe(
            'Whether SCIM provisioning is enabled. Setting this true generates a bearer token (returned once); setting it false clears the token.'
        ),
    id_jag_issuer_url: zod
        .string()
        .max(identityProviderConfigsPartialUpdateBodyIdJagIssuerUrlMax)
        .nullish()
        .describe('Trusted IdP issuer URL for ID-JAG (XAA). Required to enable ID-JAG.'),
    id_jag_jwks_url: zod
        .string()
        .max(identityProviderConfigsPartialUpdateBodyIdJagJwksUrlMax)
        .nullish()
        .describe('Override JWKS URL. Defaults to OIDC discovery on the issuer URL.'),
    id_jag_allowed_clients: zod
        .array(zod.string().max(identityProviderConfigsPartialUpdateBodyIdJagAllowedClientsItemMax))
        .optional()
        .describe('Allowed ID-JAG client IDs. Empty list allows any client_id.'),
})

export const invitesCreateBodyTargetEmailMax = 254

export const invitesCreateBodyFirstNameMax = 30

export const invitesCreateBodySendEmailDefault = true
export const invitesCreateBodyCombinePendingInvitesDefault = false

export const InvitesCreateBody = /* @__PURE__ */ zod.object({
    target_email: zod.email().max(invitesCreateBodyTargetEmailMax),
    first_name: zod.string().max(invitesCreateBodyFirstNameMax).optional(),
    level: zod
        .union([zod.literal(1), zod.literal(8), zod.literal(15)])
        .optional()
        .describe('\* `1` - member\n\* `8` - administrator\n\* `15` - owner'),
    message: zod.string().nullish(),
    private_project_access: zod
        .unknown()
        .optional()
        .describe('List of team IDs and corresponding access levels to private projects.'),
    send_email: zod.boolean().default(invitesCreateBodySendEmailDefault),
    combine_pending_invites: zod.boolean().default(invitesCreateBodyCombinePendingInvitesDefault),
})

export const invitesBulkCreateBodyTargetEmailMax = 254

export const invitesBulkCreateBodyFirstNameMax = 30

export const invitesBulkCreateBodySendEmailDefault = true
export const invitesBulkCreateBodyCombinePendingInvitesDefault = false

export const InvitesBulkCreateBody = /* @__PURE__ */ zod.object({
    target_email: zod.email().max(invitesBulkCreateBodyTargetEmailMax),
    first_name: zod.string().max(invitesBulkCreateBodyFirstNameMax).optional(),
    level: zod
        .union([zod.literal(1), zod.literal(8), zod.literal(15)])
        .optional()
        .describe('\* `1` - member\n\* `8` - administrator\n\* `15` - owner'),
    message: zod.string().nullish(),
    private_project_access: zod
        .unknown()
        .optional()
        .describe('List of team IDs and corresponding access levels to private projects.'),
    send_email: zod.boolean().default(invitesBulkCreateBodySendEmailDefault),
    combine_pending_invites: zod.boolean().default(invitesBulkCreateBodyCombinePendingInvitesDefault),
})

/**
 * Create an onboarding delegation invite: an admin-level invite flagged as a setup delegation.
 * Sends a single dedicated delegation email and records the inviting user as having delegated.
 */
export const invitesDelegateCreateBodyMessageMax = 1000

export const invitesDelegateCreateBodyStepAtDelegationMax = 64

export const InvitesDelegateCreateBody = /* @__PURE__ */ zod.object({
    target_email: zod
        .email()
        .describe(
            "Email of the teammate who should complete setup on the inviter's behalf. Receives a PostHog-branded delegation invite granting admin-level membership on accept."
        ),
    message: zod
        .string()
        .max(invitesDelegateCreateBodyMessageMax)
        .optional()
        .describe('Optional personal message included in the delegation email (up to 1000 characters).'),
    step_at_delegation: zod
        .string()
        .max(invitesDelegateCreateBodyStepAtDelegationMax)
        .optional()
        .describe('Onboarding step key the delegator was on when delegating, for analytics only.'),
})

/**
 * Projects for the current organization.
 */
export const OrganizationsProjectsCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Replace a project and its settings. Prefer the PATCH endpoint for partial updates — PUT requires every writable field to be provided.
 */
export const OrganizationsProjectsUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Update one or more of a project's settings. Only the fields included in the request body are changed.
 */
export const OrganizationsProjectsPartialUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Projects for the current organization.
 */
export const OrganizationsProjectsAddProductIntentPartialUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Projects for the current organization.
 */
export const OrganizationsProjectsChangeOrganizationCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Projects for the current organization.
 */
export const OrganizationsProjectsCompleteProductOnboardingPartialUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Manage default evaluation contexts for a project.
 */
export const OrganizationsProjectsDefaultEvaluationContextsCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Manage default release conditions for new feature flags in this project.
 */
export const OrganizationsProjectsDefaultReleaseConditionsUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Projects for the current organization.
 */
export const OrganizationsProjectsDeleteSecretTokenBackupPartialUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Manage experiment configuration for this project.
 */
export const OrganizationsProjectsExperimentsConfigPartialUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Projects for the current organization.
 */
export const OrganizationsProjectsGenerateConversationsPublicTokenCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Manage logs product configuration for this project's canonical environment.
 * Members can read; writing requires project admin, matching the admin-only
 * settings UI. Mirrors the env-router action so /api/projects/:id/logs_config/
 * resolves alongside the legacy /api/environments/:id/logs_config/ alias.
 */
export const OrganizationsProjectsLogsConfigPartialUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Projects for the current organization.
 */
export const OrganizationsProjectsResetTokenPartialUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Projects for the current organization.
 */
export const OrganizationsProjectsRotateSecretTokenPartialUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Create a new password for the sharing configuration.
 */
export const DashboardsSharingPasswordsCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().optional(),
    password_required: zod.boolean().optional(),
})

export const DashboardsSharingRefreshCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().optional(),
    password_required: zod.boolean().optional(),
})

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const desktopFileSystemCreateBodyTypeMax = 100

export const desktopFileSystemCreateBodyRefMax = 100

export const DesktopFileSystemCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(desktopFileSystemCreateBodyTypeMax).optional(),
    ref: zod.string().max(desktopFileSystemCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const desktopFileSystemUpdateBodyTypeMax = 100

export const desktopFileSystemUpdateBodyRefMax = 100

export const DesktopFileSystemUpdateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(desktopFileSystemUpdateBodyTypeMax).optional(),
    ref: zod.string().max(desktopFileSystemUpdateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const desktopFileSystemPartialUpdateBodyTypeMax = 100

export const desktopFileSystemPartialUpdateBodyRefMax = 100

export const DesktopFileSystemPartialUpdateBody = /* @__PURE__ */ zod.object({
    path: zod.string().optional(),
    type: zod.string().max(desktopFileSystemPartialUpdateBodyTypeMax).optional(),
    ref: zod.string().max(desktopFileSystemPartialUpdateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

/**
 * Publish a new version of a freeform canvas's React source.
 *
 * Merges into the dashboard row's `meta` (never replaces it), so existing
 * keys like `channelId`/`templateId` survive. Appends a full-file version
 * snapshot and points `currentVersionId` at it — the server-side mirror of
 * the app's dashboardsService.saveFreeform.
 */
export const DesktopFileSystemCanvasPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        code: zod.string().optional(),
        prompt: zod.string().optional(),
        name: zod.string().optional(),
    })
    .describe("Payload for publishing a freeform canvas's React source via the agent.")

/**
 * Set or clear the Task associated with this folder's CONTEXT.md generation.
 */
export const DesktopFileSystemContextGenerationUpdateBody = /* @__PURE__ */ zod.object({
    task_id: zod
        .uuid()
        .nullable()
        .describe(
            "ID of the Task generating this folder's CONTEXT.md. Must reference a Task in the same team. Set to null to clear the association."
        ),
})

/**
 * Get count of all files in a folder.
 */
export const desktopFileSystemCountCreateBodyTypeMax = 100

export const desktopFileSystemCountCreateBodyRefMax = 100

export const DesktopFileSystemCountCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(desktopFileSystemCountCreateBodyTypeMax).optional(),
    ref: zod.string().max(desktopFileSystemCountCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

/**
 * Publish a new version of the folder's instructions.
 */
export const desktopFileSystemInstructionsUpdateBodyBaseVersionMin = 0

export const DesktopFileSystemInstructionsUpdateBody = /* @__PURE__ */ zod.object({
    content: zod.string().describe('Full markdown instructions to publish as a new version for the folder.'),
    base_version: zod
        .number()
        .min(desktopFileSystemInstructionsUpdateBodyBaseVersionMin)
        .optional()
        .describe(
            "Latest version you are editing from, for optimistic concurrency. If provided and the folder's instructions have changed since, the request fails with 409. Use 0 when no instructions exist yet."
        ),
})

/**
 * Publish a new version of the folder's instructions.
 */
export const desktopFileSystemInstructionsPartialUpdateBodyBaseVersionMin = 0

export const DesktopFileSystemInstructionsPartialUpdateBody = /* @__PURE__ */ zod.object({
    content: zod.string().optional().describe('Full markdown instructions to publish as a new version for the folder.'),
    base_version: zod
        .number()
        .min(desktopFileSystemInstructionsPartialUpdateBodyBaseVersionMin)
        .optional()
        .describe(
            "Latest version you are editing from, for optimistic concurrency. If provided and the folder's instructions have changed since, the request fails with 409. Use 0 when no instructions exist yet."
        ),
})

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const desktopFileSystemLinkCreateBodyTypeMax = 100

export const desktopFileSystemLinkCreateBodyRefMax = 100

export const DesktopFileSystemLinkCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(desktopFileSystemLinkCreateBodyTypeMax).optional(),
    ref: zod.string().max(desktopFileSystemLinkCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const desktopFileSystemMoveCreateBodyTypeMax = 100

export const desktopFileSystemMoveCreateBodyRefMax = 100

export const DesktopFileSystemMoveCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(desktopFileSystemMoveCreateBodyTypeMax).optional(),
    ref: zod.string().max(desktopFileSystemMoveCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

/**
 * Get count of all files in a folder.
 */
export const desktopFileSystemCountByPathCreateBodyTypeMax = 100

export const desktopFileSystemCountByPathCreateBodyRefMax = 100

export const DesktopFileSystemCountByPathCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(desktopFileSystemCountByPathCreateBodyTypeMax).optional(),
    ref: zod.string().max(desktopFileSystemCountByPathCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const desktopFileSystemLogViewCreateBodyTypeMax = 100

export const desktopFileSystemLogViewCreateBodyRefMax = 100

export const DesktopFileSystemLogViewCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(desktopFileSystemLogViewCreateBodyTypeMax).optional(),
    ref: zod.string().max(desktopFileSystemLogViewCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const desktopFileSystemUndoDeleteCreateBodyTypeMax = 100

export const desktopFileSystemUndoDeleteCreateBodyRefMax = 100

export const DesktopFileSystemUndoDeleteCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(desktopFileSystemUndoDeleteCreateBodyTypeMax).optional(),
    ref: zod.string().max(desktopFileSystemUndoDeleteCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

/**
 * Sidebar shortcuts for the desktop product surface. Reuses all FileSystemShortcutViewSet
 * behaviour but is scoped to the "desktop" surface, so its shortcuts are fully isolated from
 * the default "web" surface.
 */
export const desktopFileSystemShortcutCreateBodyTypeMax = 100

export const desktopFileSystemShortcutCreateBodyRefMax = 100

export const desktopFileSystemShortcutCreateBodyOrderMin = -2147483648
export const desktopFileSystemShortcutCreateBodyOrderMax = 2147483647

export const DesktopFileSystemShortcutCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string().describe('Display path of the shortcut in the sidebar.'),
    type: zod
        .string()
        .max(desktopFileSystemShortcutCreateBodyTypeMax)
        .optional()
        .describe("Type of the linked item (e.g. 'folder', 'insight'), or blank."),
    ref: zod
        .string()
        .max(desktopFileSystemShortcutCreateBodyRefMax)
        .nullish()
        .describe('Reference to the linked item, scoped to its type. Null for href-only shortcuts.'),
    href: zod
        .string()
        .nullish()
        .describe('Destination URL the shortcut opens. Null when the shortcut points at an item by ref.'),
    order: zod
        .number()
        .min(desktopFileSystemShortcutCreateBodyOrderMin)
        .max(desktopFileSystemShortcutCreateBodyOrderMax)
        .optional()
        .describe("Display order within the user's shortcut list, ascending."),
})

/**
 * Sidebar shortcuts for the desktop product surface. Reuses all FileSystemShortcutViewSet
 * behaviour but is scoped to the "desktop" surface, so its shortcuts are fully isolated from
 * the default "web" surface.
 */
export const desktopFileSystemShortcutUpdateBodyTypeMax = 100

export const desktopFileSystemShortcutUpdateBodyRefMax = 100

export const desktopFileSystemShortcutUpdateBodyOrderMin = -2147483648
export const desktopFileSystemShortcutUpdateBodyOrderMax = 2147483647

export const DesktopFileSystemShortcutUpdateBody = /* @__PURE__ */ zod.object({
    path: zod.string().describe('Display path of the shortcut in the sidebar.'),
    type: zod
        .string()
        .max(desktopFileSystemShortcutUpdateBodyTypeMax)
        .optional()
        .describe("Type of the linked item (e.g. 'folder', 'insight'), or blank."),
    ref: zod
        .string()
        .max(desktopFileSystemShortcutUpdateBodyRefMax)
        .nullish()
        .describe('Reference to the linked item, scoped to its type. Null for href-only shortcuts.'),
    href: zod
        .string()
        .nullish()
        .describe('Destination URL the shortcut opens. Null when the shortcut points at an item by ref.'),
    order: zod
        .number()
        .min(desktopFileSystemShortcutUpdateBodyOrderMin)
        .max(desktopFileSystemShortcutUpdateBodyOrderMax)
        .optional()
        .describe("Display order within the user's shortcut list, ascending."),
})

/**
 * Sidebar shortcuts for the desktop product surface. Reuses all FileSystemShortcutViewSet
 * behaviour but is scoped to the "desktop" surface, so its shortcuts are fully isolated from
 * the default "web" surface.
 */
export const desktopFileSystemShortcutPartialUpdateBodyTypeMax = 100

export const desktopFileSystemShortcutPartialUpdateBodyRefMax = 100

export const desktopFileSystemShortcutPartialUpdateBodyOrderMin = -2147483648
export const desktopFileSystemShortcutPartialUpdateBodyOrderMax = 2147483647

export const DesktopFileSystemShortcutPartialUpdateBody = /* @__PURE__ */ zod.object({
    path: zod.string().optional().describe('Display path of the shortcut in the sidebar.'),
    type: zod
        .string()
        .max(desktopFileSystemShortcutPartialUpdateBodyTypeMax)
        .optional()
        .describe("Type of the linked item (e.g. 'folder', 'insight'), or blank."),
    ref: zod
        .string()
        .max(desktopFileSystemShortcutPartialUpdateBodyRefMax)
        .nullish()
        .describe('Reference to the linked item, scoped to its type. Null for href-only shortcuts.'),
    href: zod
        .string()
        .nullish()
        .describe('Destination URL the shortcut opens. Null when the shortcut points at an item by ref.'),
    order: zod
        .number()
        .min(desktopFileSystemShortcutPartialUpdateBodyOrderMin)
        .max(desktopFileSystemShortcutPartialUpdateBodyOrderMax)
        .optional()
        .describe("Display order within the user's shortcut list, ascending."),
})

/**
 * Set the display order of the current user's shortcuts. `ordered_ids` becomes the new top-to-bottom order; any unknown IDs are rejected.
 */
export const DesktopFileSystemShortcutReorderCreateBody = /* @__PURE__ */ zod.object({
    ordered_ids: zod.array(zod.uuid()).describe("IDs of the current user's shortcuts in the desired display order."),
})

export const ExportsCreateBody = /* @__PURE__ */ zod
    .object({
        dashboard: zod.number().nullish(),
        insight: zod.number().nullish(),
        export_format: zod
            .enum([
                'image/png',
                'application/pdf',
                'text/csv',
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'video/webm',
                'video/mp4',
                'image/gif',
                'application/json',
            ])
            .describe(
                '\* `image\/png` - image\/png\n\* `application\/pdf` - application\/pdf\n\* `text\/csv` - text\/csv\n\* `application\/vnd.openxmlformats-officedocument.spreadsheetml.sheet` - application\/vnd.openxmlformats-officedocument.spreadsheetml.sheet\n\* `video\/webm` - video\/webm\n\* `video\/mp4` - video\/mp4\n\* `image\/gif` - image\/gif\n\* `application\/json` - application\/json'
            ),
        export_context: zod.unknown().optional(),
    })
    .describe("Standard ExportedAsset serializer that doesn't return content.")

export const fileSystemCreateBodyTypeMax = 100

export const fileSystemCreateBodyRefMax = 100

export const FileSystemCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(fileSystemCreateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

export const fileSystemUpdateBodyTypeMax = 100

export const fileSystemUpdateBodyRefMax = 100

export const FileSystemUpdateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(fileSystemUpdateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemUpdateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

export const fileSystemPartialUpdateBodyTypeMax = 100

export const fileSystemPartialUpdateBodyRefMax = 100

export const FileSystemPartialUpdateBody = /* @__PURE__ */ zod.object({
    path: zod.string().optional(),
    type: zod.string().max(fileSystemPartialUpdateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemPartialUpdateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

/**
 * Get count of all files in a folder.
 */
export const fileSystemCountCreateBodyTypeMax = 100

export const fileSystemCountCreateBodyRefMax = 100

export const FileSystemCountCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(fileSystemCountCreateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemCountCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

export const fileSystemLinkCreateBodyTypeMax = 100

export const fileSystemLinkCreateBodyRefMax = 100

export const FileSystemLinkCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(fileSystemLinkCreateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemLinkCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

export const fileSystemMoveCreateBodyTypeMax = 100

export const fileSystemMoveCreateBodyRefMax = 100

export const FileSystemMoveCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(fileSystemMoveCreateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemMoveCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

/**
 * Get count of all files in a folder.
 */
export const fileSystemCountByPathCreateBodyTypeMax = 100

export const fileSystemCountByPathCreateBodyRefMax = 100

export const FileSystemCountByPathCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(fileSystemCountByPathCreateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemCountByPathCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

export const fileSystemLogViewCreateBodyTypeMax = 100

export const fileSystemLogViewCreateBodyRefMax = 100

export const FileSystemLogViewCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(fileSystemLogViewCreateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemLogViewCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

export const fileSystemUndoDeleteCreateBodyTypeMax = 100

export const fileSystemUndoDeleteCreateBodyRefMax = 100

export const FileSystemUndoDeleteCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(fileSystemUndoDeleteCreateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemUndoDeleteCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

export const fileSystemShortcutCreateBodyTypeMax = 100

export const fileSystemShortcutCreateBodyRefMax = 100

export const fileSystemShortcutCreateBodyOrderMin = -2147483648
export const fileSystemShortcutCreateBodyOrderMax = 2147483647

export const FileSystemShortcutCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string().describe('Display path of the shortcut in the sidebar.'),
    type: zod
        .string()
        .max(fileSystemShortcutCreateBodyTypeMax)
        .optional()
        .describe("Type of the linked item (e.g. 'folder', 'insight'), or blank."),
    ref: zod
        .string()
        .max(fileSystemShortcutCreateBodyRefMax)
        .nullish()
        .describe('Reference to the linked item, scoped to its type. Null for href-only shortcuts.'),
    href: zod
        .string()
        .nullish()
        .describe('Destination URL the shortcut opens. Null when the shortcut points at an item by ref.'),
    order: zod
        .number()
        .min(fileSystemShortcutCreateBodyOrderMin)
        .max(fileSystemShortcutCreateBodyOrderMax)
        .optional()
        .describe("Display order within the user's shortcut list, ascending."),
})

export const fileSystemShortcutUpdateBodyTypeMax = 100

export const fileSystemShortcutUpdateBodyRefMax = 100

export const fileSystemShortcutUpdateBodyOrderMin = -2147483648
export const fileSystemShortcutUpdateBodyOrderMax = 2147483647

export const FileSystemShortcutUpdateBody = /* @__PURE__ */ zod.object({
    path: zod.string().describe('Display path of the shortcut in the sidebar.'),
    type: zod
        .string()
        .max(fileSystemShortcutUpdateBodyTypeMax)
        .optional()
        .describe("Type of the linked item (e.g. 'folder', 'insight'), or blank."),
    ref: zod
        .string()
        .max(fileSystemShortcutUpdateBodyRefMax)
        .nullish()
        .describe('Reference to the linked item, scoped to its type. Null for href-only shortcuts.'),
    href: zod
        .string()
        .nullish()
        .describe('Destination URL the shortcut opens. Null when the shortcut points at an item by ref.'),
    order: zod
        .number()
        .min(fileSystemShortcutUpdateBodyOrderMin)
        .max(fileSystemShortcutUpdateBodyOrderMax)
        .optional()
        .describe("Display order within the user's shortcut list, ascending."),
})

export const fileSystemShortcutPartialUpdateBodyTypeMax = 100

export const fileSystemShortcutPartialUpdateBodyRefMax = 100

export const fileSystemShortcutPartialUpdateBodyOrderMin = -2147483648
export const fileSystemShortcutPartialUpdateBodyOrderMax = 2147483647

export const FileSystemShortcutPartialUpdateBody = /* @__PURE__ */ zod.object({
    path: zod.string().optional().describe('Display path of the shortcut in the sidebar.'),
    type: zod
        .string()
        .max(fileSystemShortcutPartialUpdateBodyTypeMax)
        .optional()
        .describe("Type of the linked item (e.g. 'folder', 'insight'), or blank."),
    ref: zod
        .string()
        .max(fileSystemShortcutPartialUpdateBodyRefMax)
        .nullish()
        .describe('Reference to the linked item, scoped to its type. Null for href-only shortcuts.'),
    href: zod
        .string()
        .nullish()
        .describe('Destination URL the shortcut opens. Null when the shortcut points at an item by ref.'),
    order: zod
        .number()
        .min(fileSystemShortcutPartialUpdateBodyOrderMin)
        .max(fileSystemShortcutPartialUpdateBodyOrderMax)
        .optional()
        .describe("Display order within the user's shortcut list, ascending."),
})

/**
 * Set the display order of the current user's shortcuts. `ordered_ids` becomes the new top-to-bottom order; any unknown IDs are rejected.
 */
export const FileSystemShortcutReorderCreateBody = /* @__PURE__ */ zod.object({
    ordered_ids: zod.array(zod.uuid()).describe("IDs of the current user's shortcuts in the desired display order."),
})

/**
 * Create a new password for the sharing configuration.
 */
export const InsightsSharingPasswordsCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().optional(),
    password_required: zod.boolean().optional(),
})

export const InsightsSharingRefreshCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().optional(),
    password_required: zod.boolean().optional(),
})

/**
 * Create a new password for the sharing configuration.
 */
export const NotebooksSharingPasswordsCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().optional(),
    password_required: zod.boolean().optional(),
})

export const NotebooksSharingRefreshCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().optional(),
    password_required: zod.boolean().optional(),
})

export const ProductEnablementCreateBody = /* @__PURE__ */ zod.object({
    products: zod
        .array(
            zod
                .enum(['conversations', 'error_tracking', 'session_replay'])
                .describe(
                    '\* `conversations` - conversations\n\* `error_tracking` - error_tracking\n\* `session_replay` - session_replay'
                )
        )
        .min(1)
        .describe('Products to turn on for this project, each enabled with server-owned conservative defaults.'),
})

export const projectSecretApiKeysCreateBodyLabelMax = 40

export const ProjectSecretApiKeysCreateBody = /* @__PURE__ */ zod.object({
    label: zod.string().max(projectSecretApiKeysCreateBodyLabelMax),
    scopes: zod
        .array(zod.string())
        .describe(
            'Project-wide API scopes granted to this key. Project secret API keys do not honor object-level access controls, so a scope can access resources of that type even when per-resource RBAC would hide them from an individual user.'
        ),
})

export const projectSecretApiKeysUpdateBodyLabelMax = 40

export const ProjectSecretApiKeysUpdateBody = /* @__PURE__ */ zod.object({
    label: zod.string().max(projectSecretApiKeysUpdateBodyLabelMax),
    scopes: zod
        .array(zod.string())
        .describe(
            'Project-wide API scopes granted to this key. Project secret API keys do not honor object-level access controls, so a scope can access resources of that type even when per-resource RBAC would hide them from an individual user.'
        ),
})

export const projectSecretApiKeysPartialUpdateBodyLabelMax = 40

export const ProjectSecretApiKeysPartialUpdateBody = /* @__PURE__ */ zod.object({
    label: zod.string().max(projectSecretApiKeysPartialUpdateBodyLabelMax).optional(),
    scopes: zod
        .array(zod.string())
        .optional()
        .describe(
            'Project-wide API scopes granted to this key. Project secret API keys do not honor object-level access controls, so a scope can access resources of that type even when per-resource RBAC would hide them from an individual user.'
        ),
})

export const PropertyDefinitionsUpdateBody = /* @__PURE__ */ zod
    .object({
        description: zod.string().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        property_type: zod
            .union([
                zod
                    .enum(['DateTime', 'String', 'Numeric', 'Boolean', 'Duration'])
                    .describe(
                        '\* `DateTime` - DateTime\n\* `String` - String\n\* `Numeric` - Numeric\n\* `Boolean` - Boolean\n\* `Duration` - Duration'
                    ),
                zod.enum(['']),
                zod.null(),
            ])
            .optional(),
        verified: zod.boolean().optional(),
        hidden: zod.boolean().nullish(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const PropertyDefinitionsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        description: zod.string().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        property_type: zod
            .union([
                zod
                    .enum(['DateTime', 'String', 'Numeric', 'Boolean', 'Duration'])
                    .describe(
                        '\* `DateTime` - DateTime\n\* `String` - String\n\* `Numeric` - Numeric\n\* `Boolean` - Boolean\n\* `Duration` - Duration'
                    ),
                zod.enum(['']),
                zod.null(),
            ])
            .optional(),
        verified: zod.boolean().optional(),
        hidden: zod.boolean().nullish(),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Bulk update tags on multiple objects.
 *
 * PAT access: this action has no ``required_scopes=`` on the decorator —
 * inheriting viewsets must add ``"bulk_update_tags"`` to their
 * ``scope_object_write_actions`` list to accept personal API keys.
 * Without that opt-in, ``APIScopePermission`` rejects PAT requests with
 * "This action does not support personal API key access". Done per-viewset
 * so granting ``<scope>:write`` for one resource doesn't leak access to
 * sibling resources that share this mixin.
 *
 * Accepts:
 * - {"ids": [...], "action": "add"|"remove"|"set", "tags": ["tag1", "tag2"]}
 *
 * Actions:
 * - "add": Add tags to existing tags on each object
 * - "remove": Remove specific tags from each object
 * - "set": Replace all tags on each object with the provided list
 */
export const propertyDefinitionsBulkUpdateTagsCreateBodyIdsMax = 500

export const PropertyDefinitionsBulkUpdateTagsCreateBody = /* @__PURE__ */ zod.object({
    ids: zod
        .array(zod.number())
        .max(propertyDefinitionsBulkUpdateTagsCreateBodyIdsMax)
        .describe('List of object IDs to update tags on.'),
    action: zod
        .enum(['add', 'remove', 'set'])
        .describe('\* `add` - add\n\* `remove` - remove\n\* `set` - set')
        .describe(
            "'add' merges with existing tags, 'remove' deletes specific tags, 'set' replaces all tags.\n\n\* `add` - add\n\* `remove` - remove\n\* `set` - set"
        ),
    tags: zod.array(zod.string()).describe('Tag names to add, remove, or set.'),
})

/**
 * Create a new password for the sharing configuration.
 */
export const SessionRecordingsSharingPasswordsCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().optional(),
    password_required: zod.boolean().optional(),
})

export const SessionRecordingsSharingRefreshCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().optional(),
    password_required: zod.boolean().optional(),
})

/**
 * Replace the authenticated user's profile and settings. Pass `@me` as the UUID to update the authenticated user. Prefer the PATCH endpoint for partial updates — PUT requires every writable field to be provided.
 */
export const usersUpdateBodyFirstNameMax = 150

export const usersUpdateBodyLastNameMax = 150

export const usersUpdateBodyEmailMax = 254

export const usersUpdateBodyPasswordMax = 128

export const UsersUpdateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersUpdateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersUpdateBodyLastNameMax).optional(),
    email: zod.email().max(usersUpdateBodyEmailMax),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project\/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('\* `disabled` - disabled\n\* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersUpdateBodyPasswordMax),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().optional(),
    theme_mode: zod
        .union([
            zod
                .enum(['light', 'dark', 'system'])
                .describe('\* `light` - Light\n\* `dark` - Dark\n\* `system` - System'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    hedgehog_config: zod.unknown().optional(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('\* `above` - Above\n\* `below` - Below\n\* `hidden` - Hidden'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
    hide_mcp_hints: zod
        .boolean()
        .optional()
        .describe(
            'When true, the user has opted out of in-app hints promoting the PostHog MCP integration after taking actions.'
        ),
})

/**
 * Update one or more of the authenticated user's profile fields or settings.
 */
export const usersPartialUpdateBodyFirstNameMax = 150

export const usersPartialUpdateBodyLastNameMax = 150

export const usersPartialUpdateBodyEmailMax = 254

export const usersPartialUpdateBodyPasswordMax = 128

export const UsersPartialUpdateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersPartialUpdateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersPartialUpdateBodyLastNameMax).optional(),
    email: zod.email().max(usersPartialUpdateBodyEmailMax).optional(),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project\/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('\* `disabled` - disabled\n\* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersPartialUpdateBodyPasswordMax).optional(),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().optional(),
    theme_mode: zod
        .union([
            zod
                .enum(['light', 'dark', 'system'])
                .describe('\* `light` - Light\n\* `dark` - Dark\n\* `system` - System'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    hedgehog_config: zod.unknown().optional(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('\* `above` - Above\n\* `below` - Below\n\* `hidden` - Hidden'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
    hide_mcp_hints: zod
        .boolean()
        .optional()
        .describe(
            'When true, the user has opted out of in-app hints promoting the PostHog MCP integration after taking actions.'
        ),
})

export const usersHedgehogConfigPartialUpdateBodyFirstNameMax = 150

export const usersHedgehogConfigPartialUpdateBodyLastNameMax = 150

export const usersHedgehogConfigPartialUpdateBodyEmailMax = 254

export const usersHedgehogConfigPartialUpdateBodyPasswordMax = 128

export const UsersHedgehogConfigPartialUpdateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersHedgehogConfigPartialUpdateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersHedgehogConfigPartialUpdateBodyLastNameMax).optional(),
    email: zod.email().max(usersHedgehogConfigPartialUpdateBodyEmailMax).optional(),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project\/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('\* `disabled` - disabled\n\* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersHedgehogConfigPartialUpdateBodyPasswordMax).optional(),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().optional(),
    theme_mode: zod
        .union([
            zod
                .enum(['light', 'dark', 'system'])
                .describe('\* `light` - Light\n\* `dark` - Dark\n\* `system` - System'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    hedgehog_config: zod.unknown().optional(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('\* `above` - Above\n\* `below` - Below\n\* `hidden` - Hidden'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
    hide_mcp_hints: zod
        .boolean()
        .optional()
        .describe(
            'When true, the user has opted out of in-app hints promoting the PostHog MCP integration after taking actions.'
        ),
})

/**
 * Seed personal GitHub manage callback state before opening installation settings on GitHub.
 */
export const UsersIntegrationsGithubPrepareCallbackCreateBody = /* @__PURE__ */ zod.object({
    installation_id: zod.string().describe('GitHub App installation id being managed on github.com.'),
})

/**
 * Start GitHub linking: either full App install or OAuth-only (user-to-server).
 *
 * ``**_kwargs`` absorbs ``parent_lookup_uuid`` from the nested
 * ``/api/users/{uuid}/integrations/`` router (same pattern as ``local_evaluation``
 * under projects).
 *
 * Usually returns ``install_url`` pointing at ``/installations/new`` so the
 * user can pick any GitHub org (new or already connected).  GitHub's install
 * page handles both cases: orgs where the app is installed show "Configure"
 * (no admin needed), orgs where it isn't show "Install" (needs admin).
 *
 * **OAuth fast path:** when the current project already has a team-level
 * GitHub installation, and the user has no ``UserIntegration`` for that
 * installation yet, we skip the org picker and redirect straight to
 * ``/login/oauth/authorize`` so the user only authorizes themselves.
 * ``connect_from`` is preserved for first-party clients so they return to
 * the originating client immediately.
 *
 * In both cases the response key is ``install_url`` for compatibility with callers.
 * @summary Start GitHub personal integration linking
 */
export const UsersIntegrationsGithubStartCreateBody = /* @__PURE__ */ zod.object({
    team_id: zod
        .number()
        .nullish()
        .describe("Optional team\/project id (e.g. PostHog Code); web UI uses the session's current team."),
    connect_from: zod
        .string()
        .optional()
        .describe('Optional client hint (e.g. posthog_code) for return routing after OAuth.'),
})

/**
 * Mint a Sign-in-with-Slack invite URL initiated from settings, without
 * Slack-DM context. The returned URL takes the user through PostHog login
 * (already satisfied here), then to Slack OAuth, then back to our callback
 * which writes the ``UserIntegration`` row.
 *
 * Without body params, falls back to the user's ``current_team`` and that
 * team's first Slack ``Integration`` — works when there's exactly one
 * linkable workspace. With ``team_id`` + ``slack_team_id``, links against
 * the exact pair (what the frontend uses when a picker is shown).
 *
 * Refuses if the target team has no matching Slack workspace, if the
 * feature flag is off for the workspace, or if the user is already linked
 * to it.
 * @summary Start Slack identity link from settings
 */
export const UsersIntegrationsSlackStartCreateBody = /* @__PURE__ */ zod
    .object({
        team_id: zod
            .number()
            .nullish()
            .describe("Optional team\/project id to link against; defaults to the user's current team."),
        slack_team_id: zod
            .string()
            .nullish()
            .describe(
                'Specific Slack workspace id to link against, scoped to the team. Disambiguates when one team has multiple Slack integrations (rare).'
            ),
    })
    .describe(
        "Settings-initiated link can target a specific PostHog team + Slack workspace.\n\nBoth are optional — when omitted we fall back to the user's ``current_team``\nand that team's first Slack ``Integration`` (mirrors ``github_start`` for\nthe simple case). The frontend passes both explicitly once it has the\nlinkable-workspace list and the user has picked a workspace."
    )

/**
 * Mark the current user as having exited onboarding with a non-delegated reason.
 * Idempotent: the skip timestamp is only set on the first successful call.
 *
 * Callers wanting to delegate setup to a teammate must use the dedicated
 * /organizations/{id}/invites/delegate/ endpoint, which atomically creates the
 * invite and sets reason="delegated". This endpoint rejects that reason so state
 * can't be faked without a real invite.
 */
export const usersOnboardingSkipCreateBodyStepAtSkipMax = 64

export const UsersOnboardingSkipCreateBody = /* @__PURE__ */ zod
    .object({
        reason: zod
            .enum(['later', 'other'])
            .describe('\* `later` - Later\n\* `other` - Other')
            .describe(
                "Why the user is leaving onboarding. 'later' keeps them able to return; 'other' is a catch-all. 'delegated' is rejected here — use the delegate endpoint so the delegation invite is created atomically.\n\n\* `later` - Later\n\* `other` - Other"
            ),
        step_at_skip: zod
            .string()
            .max(usersOnboardingSkipCreateBodyStepAtSkipMax)
            .optional()
            .describe('Onboarding step key the user was on when skipping, for analytics only.'),
    })
    .describe(
        'Request body for POST \/api\/users\/{id}\/onboarding\/skip\/.\n\nSource of truth for OpenAPI \/ generated TS \/ zod \/ MCP — bind this serializer at\nruntime so the contract clients believe is enforced (length cap, choice validation,\nno extra fields) is actually enforced server-side.'
    )

/**
 * Idempotent upsert: if the (user, token) pair already exists, `platform` and `last_seen_at` are refreshed. Otherwise a new row is created.
 * @summary Register a push notification token
 */
export const usersPushTokensCreateBodyTokenMax = 512

export const UsersPushTokensCreateBody = /* @__PURE__ */ zod.object({
    token: zod
        .string()
        .max(usersPushTokensCreateBodyTokenMax)
        .describe("Opaque push token issued by the device's platform push service (e.g. an Expo push token)."),
    platform: zod
        .enum(['ios', 'android', 'web'])
        .describe('\* `ios` - iOS\n\* `android` - Android\n\* `web` - Web')
        .describe(
            'Device platform the token was issued for. One of `ios`, `android`, or `web`.\n\n\* `ios` - iOS\n\* `android` - Android\n\* `web` - Web'
        ),
})

/**
 * Delete the row matching `(user, token)`. Returns 204 even if no row matches so the mobile client can call this unconditionally when the user opts out.
 * @summary Unregister a push notification token
 */
export const usersPushTokensUnregisterCreateBodyTokenMax = 512

export const UsersPushTokensUnregisterCreateBody = /* @__PURE__ */ zod.object({
    token: zod
        .string()
        .max(usersPushTokensUnregisterCreateBodyTokenMax)
        .describe('The opaque push token to remove for the authenticated user.'),
})

export const usersScenePersonalisationCreateBodyFirstNameMax = 150

export const usersScenePersonalisationCreateBodyLastNameMax = 150

export const usersScenePersonalisationCreateBodyEmailMax = 254

export const usersScenePersonalisationCreateBodyPasswordMax = 128

export const UsersScenePersonalisationCreateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersScenePersonalisationCreateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersScenePersonalisationCreateBodyLastNameMax).optional(),
    email: zod.email().max(usersScenePersonalisationCreateBodyEmailMax),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project\/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('\* `disabled` - disabled\n\* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersScenePersonalisationCreateBodyPasswordMax),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().optional(),
    theme_mode: zod
        .union([
            zod
                .enum(['light', 'dark', 'system'])
                .describe('\* `light` - Light\n\* `dark` - Dark\n\* `system` - System'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    hedgehog_config: zod.unknown().optional(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('\* `above` - Above\n\* `below` - Below\n\* `hidden` - Hidden'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
    hide_mcp_hints: zod
        .boolean()
        .optional()
        .describe(
            'When true, the user has opted out of in-app hints promoting the PostHog MCP integration after taking actions.'
        ),
})

/**
 * Generate new backup codes, invalidating any existing ones
 */
export const usersTwoFactorBackupCodesCreateBodyFirstNameMax = 150

export const usersTwoFactorBackupCodesCreateBodyLastNameMax = 150

export const usersTwoFactorBackupCodesCreateBodyEmailMax = 254

export const usersTwoFactorBackupCodesCreateBodyPasswordMax = 128

export const UsersTwoFactorBackupCodesCreateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersTwoFactorBackupCodesCreateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersTwoFactorBackupCodesCreateBodyLastNameMax).optional(),
    email: zod.email().max(usersTwoFactorBackupCodesCreateBodyEmailMax),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project\/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('\* `disabled` - disabled\n\* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersTwoFactorBackupCodesCreateBodyPasswordMax),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().optional(),
    theme_mode: zod
        .union([
            zod
                .enum(['light', 'dark', 'system'])
                .describe('\* `light` - Light\n\* `dark` - Dark\n\* `system` - System'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    hedgehog_config: zod.unknown().optional(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('\* `above` - Above\n\* `below` - Below\n\* `hidden` - Hidden'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
    hide_mcp_hints: zod
        .boolean()
        .optional()
        .describe(
            'When true, the user has opted out of in-app hints promoting the PostHog MCP integration after taking actions.'
        ),
})

/**
 * Disable 2FA and remove all related devices
 */
export const usersTwoFactorDisableCreateBodyFirstNameMax = 150

export const usersTwoFactorDisableCreateBodyLastNameMax = 150

export const usersTwoFactorDisableCreateBodyEmailMax = 254

export const usersTwoFactorDisableCreateBodyPasswordMax = 128

export const UsersTwoFactorDisableCreateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersTwoFactorDisableCreateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersTwoFactorDisableCreateBodyLastNameMax).optional(),
    email: zod.email().max(usersTwoFactorDisableCreateBodyEmailMax),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project\/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('\* `disabled` - disabled\n\* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersTwoFactorDisableCreateBodyPasswordMax),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().optional(),
    theme_mode: zod
        .union([
            zod
                .enum(['light', 'dark', 'system'])
                .describe('\* `light` - Light\n\* `dark` - Dark\n\* `system` - System'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    hedgehog_config: zod.unknown().optional(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('\* `above` - Above\n\* `below` - Below\n\* `hidden` - Hidden'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
    hide_mcp_hints: zod
        .boolean()
        .optional()
        .describe(
            'When true, the user has opted out of in-app hints promoting the PostHog MCP integration after taking actions.'
        ),
})

export const usersTwoFactorValidateCreateBodyFirstNameMax = 150

export const usersTwoFactorValidateCreateBodyLastNameMax = 150

export const usersTwoFactorValidateCreateBodyEmailMax = 254

export const usersTwoFactorValidateCreateBodyPasswordMax = 128

export const UsersTwoFactorValidateCreateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersTwoFactorValidateCreateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersTwoFactorValidateCreateBodyLastNameMax).optional(),
    email: zod.email().max(usersTwoFactorValidateCreateBodyEmailMax),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project\/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('\* `disabled` - disabled\n\* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersTwoFactorValidateCreateBodyPasswordMax),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().optional(),
    theme_mode: zod
        .union([
            zod
                .enum(['light', 'dark', 'system'])
                .describe('\* `light` - Light\n\* `dark` - Dark\n\* `system` - System'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    hedgehog_config: zod.unknown().optional(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('\* `above` - Above\n\* `below` - Below\n\* `hidden` - Hidden'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
    hide_mcp_hints: zod
        .boolean()
        .optional()
        .describe(
            'When true, the user has opted out of in-app hints promoting the PostHog MCP integration after taking actions.'
        ),
})

export const usersValidate2faCreateBodyFirstNameMax = 150

export const usersValidate2faCreateBodyLastNameMax = 150

export const usersValidate2faCreateBodyEmailMax = 254

export const usersValidate2faCreateBodyPasswordMax = 128

export const UsersValidate2faCreateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersValidate2faCreateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersValidate2faCreateBodyLastNameMax).optional(),
    email: zod.email().max(usersValidate2faCreateBodyEmailMax),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project\/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('\* `disabled` - disabled\n\* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersValidate2faCreateBodyPasswordMax),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().optional(),
    theme_mode: zod
        .union([
            zod
                .enum(['light', 'dark', 'system'])
                .describe('\* `light` - Light\n\* `dark` - Dark\n\* `system` - System'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    hedgehog_config: zod.unknown().optional(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('\* `above` - Above\n\* `below` - Below\n\* `hidden` - Hidden'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
    hide_mcp_hints: zod
        .boolean()
        .optional()
        .describe(
            'When true, the user has opted out of in-app hints promoting the PostHog MCP integration after taking actions.'
        ),
})

export const usersCancelEmailChangeRequestPartialUpdateBodyFirstNameMax = 150

export const usersCancelEmailChangeRequestPartialUpdateBodyLastNameMax = 150

export const usersCancelEmailChangeRequestPartialUpdateBodyEmailMax = 254

export const usersCancelEmailChangeRequestPartialUpdateBodyPasswordMax = 128

export const UsersCancelEmailChangeRequestPartialUpdateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersCancelEmailChangeRequestPartialUpdateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersCancelEmailChangeRequestPartialUpdateBodyLastNameMax).optional(),
    email: zod.email().max(usersCancelEmailChangeRequestPartialUpdateBodyEmailMax).optional(),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project\/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('\* `disabled` - disabled\n\* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersCancelEmailChangeRequestPartialUpdateBodyPasswordMax).optional(),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().optional(),
    theme_mode: zod
        .union([
            zod
                .enum(['light', 'dark', 'system'])
                .describe('\* `light` - Light\n\* `dark` - Dark\n\* `system` - System'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    hedgehog_config: zod.unknown().optional(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('\* `above` - Above\n\* `below` - Below\n\* `hidden` - Hidden'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
    hide_mcp_hints: zod
        .boolean()
        .optional()
        .describe(
            'When true, the user has opted out of in-app hints promoting the PostHog MCP integration after taking actions.'
        ),
})

export const usersRequestEmailVerificationCreateBodyFirstNameMax = 150

export const usersRequestEmailVerificationCreateBodyLastNameMax = 150

export const usersRequestEmailVerificationCreateBodyEmailMax = 254

export const usersRequestEmailVerificationCreateBodyPasswordMax = 128

export const UsersRequestEmailVerificationCreateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersRequestEmailVerificationCreateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersRequestEmailVerificationCreateBodyLastNameMax).optional(),
    email: zod.email().max(usersRequestEmailVerificationCreateBodyEmailMax),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project\/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('\* `disabled` - disabled\n\* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersRequestEmailVerificationCreateBodyPasswordMax),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().optional(),
    theme_mode: zod
        .union([
            zod
                .enum(['light', 'dark', 'system'])
                .describe('\* `light` - Light\n\* `dark` - Dark\n\* `system` - System'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    hedgehog_config: zod.unknown().optional(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('\* `above` - Above\n\* `below` - Below\n\* `hidden` - Hidden'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
    hide_mcp_hints: zod
        .boolean()
        .optional()
        .describe(
            'When true, the user has opted out of in-app hints promoting the PostHog MCP integration after taking actions.'
        ),
})

export const usersVerifyEmailCreateBodyFirstNameMax = 150

export const usersVerifyEmailCreateBodyLastNameMax = 150

export const usersVerifyEmailCreateBodyEmailMax = 254

export const usersVerifyEmailCreateBodyPasswordMax = 128

export const UsersVerifyEmailCreateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersVerifyEmailCreateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersVerifyEmailCreateBodyLastNameMax).optional(),
    email: zod.email().max(usersVerifyEmailCreateBodyEmailMax),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project\/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('\* `disabled` - disabled\n\* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersVerifyEmailCreateBodyPasswordMax),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().optional(),
    theme_mode: zod
        .union([
            zod
                .enum(['light', 'dark', 'system'])
                .describe('\* `light` - Light\n\* `dark` - Dark\n\* `system` - System'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    hedgehog_config: zod.unknown().optional(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('\* `above` - Above\n\* `below` - Below\n\* `hidden` - Hidden'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
    hide_mcp_hints: zod
        .boolean()
        .optional()
        .describe(
            'When true, the user has opted out of in-app hints promoting the PostHog MCP integration after taking actions.'
        ),
})
