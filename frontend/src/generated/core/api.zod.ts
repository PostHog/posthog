/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - core
 * OpenAPI spec version: 1.0.0
 */
import {
    BulkUpdateTagsRequestApi,
    CIMDVerificationTokenApi,
    ContextGenerationSetApi,
    EnterprisePropertyDefinitionApi,
    ExportedAssetApi,
    FileSystemApi,
    FileSystemShortcutApi,
    FileSystemShortcutReorderApi,
    FolderInstructionsPublishApi,
    IdentityProviderConfigApi,
    OnboardingSkipRequestApi,
    OrganizationDomainApi,
    OrganizationInviteApi,
    OrganizationInviteDelegateApi,
    PatchedCanvasPublishApi,
    PatchedEnterprisePropertyDefinitionApi,
    PatchedFileSystemApi,
    PatchedFileSystemShortcutApi,
    PatchedFolderInstructionsPublishApi,
    PatchedIdentityProviderConfigApi,
    PatchedOrganizationDomainApi,
    PatchedProjectBackwardCompatApi,
    PatchedProjectSecretAPIKeyApi,
    PatchedUserApi,
    ProductEnablementApi,
    ProjectBackwardCompatApi,
    ProjectSecretAPIKeyApi,
    SharingConfigurationApi,
    UserApi,
    UserGitHubLinkStartRequestApi,
    UserGitHubPrepareCallbackRequestApi,
    UserPushTokenRegisterRequestApi,
    UserPushTokenUnregisterRequestApi,
    UserSlackLinkStartRequestApi,
} from './api.zod.schemas'

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
export const CimdVerificationTokensCreateBody = CIMDVerificationTokenApi

export const DomainsCreateBody = OrganizationDomainApi

export const DomainsUpdateBody = OrganizationDomainApi

export const DomainsPartialUpdateBody = PatchedOrganizationDomainApi

export const DomainsVerifyCreateBody = OrganizationDomainApi

export const IdentityProviderConfigsCreateBody = IdentityProviderConfigApi

export const IdentityProviderConfigsUpdateBody = IdentityProviderConfigApi

export const IdentityProviderConfigsPartialUpdateBody = PatchedIdentityProviderConfigApi

export const InvitesCreateBody = OrganizationInviteApi

export const InvitesBulkCreateBody = OrganizationInviteApi

/**
 * Create an onboarding delegation invite: an admin-level invite flagged as a setup delegation.
 * Sends a single dedicated delegation email and records the inviting user as having delegated.
 */
export const InvitesDelegateCreateBody = OrganizationInviteDelegateApi

/**
 * Projects for the current organization.
 */
export const OrganizationsProjectsCreateBody = ProjectBackwardCompatApi

/**
 * Replace a project and its settings. Prefer the PATCH endpoint for partial updates — PUT requires every writable field to be provided.
 */
export const OrganizationsProjectsUpdateBody = ProjectBackwardCompatApi

/**
 * Update one or more of a project's settings. Only the fields included in the request body are changed.
 */
export const OrganizationsProjectsPartialUpdateBody = PatchedProjectBackwardCompatApi

/**
 * Projects for the current organization.
 */
export const OrganizationsProjectsAddProductIntentPartialUpdateBody = PatchedProjectBackwardCompatApi

/**
 * Projects for the current organization.
 */
export const OrganizationsProjectsChangeOrganizationCreateBody = ProjectBackwardCompatApi

/**
 * Projects for the current organization.
 */
export const OrganizationsProjectsCompleteProductOnboardingPartialUpdateBody = PatchedProjectBackwardCompatApi

/**
 * Manage default evaluation contexts for a project. Members can read; writing requires
 * project admin, matching the admin-only settings UI.
 */
export const OrganizationsProjectsDefaultEvaluationContextsCreateBody = ProjectBackwardCompatApi

/**
 * Manage default release conditions for new feature flags in this project. Members can read;
 * writing requires project admin, matching the admin-only settings UI.
 */
export const OrganizationsProjectsDefaultReleaseConditionsUpdateBody = ProjectBackwardCompatApi

/**
 * Projects for the current organization.
 */
export const OrganizationsProjectsDeleteSecretTokenBackupPartialUpdateBody = PatchedProjectBackwardCompatApi

/**
 * Manage experiment configuration for this project.
 */
export const OrganizationsProjectsExperimentsConfigPartialUpdateBody = PatchedProjectBackwardCompatApi

/**
 * Projects for the current organization.
 */
export const OrganizationsProjectsGenerateConversationsPublicTokenCreateBody = ProjectBackwardCompatApi

/**
 * Manage logs product configuration for this project's canonical environment.
 * Members can read; writing requires project admin, matching the admin-only
 * settings UI. Mirrors the env-router action so /api/projects/:id/logs_config/
 * resolves alongside the legacy /api/environments/:id/logs_config/ alias.
 */
export const OrganizationsProjectsLogsConfigPartialUpdateBody = PatchedProjectBackwardCompatApi

/**
 * Projects for the current organization.
 */
export const OrganizationsProjectsResetTokenPartialUpdateBody = PatchedProjectBackwardCompatApi

/**
 * Projects for the current organization.
 */
export const OrganizationsProjectsRotateSecretTokenPartialUpdateBody = PatchedProjectBackwardCompatApi

/**
 * Create a new password for the sharing configuration.
 */
export const DashboardsSharingPasswordsCreateBody = SharingConfigurationApi

export const DashboardsSharingRefreshCreateBody = SharingConfigurationApi

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const DesktopFileSystemCreateBody = FileSystemApi

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const DesktopFileSystemUpdateBody = FileSystemApi

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const DesktopFileSystemPartialUpdateBody = PatchedFileSystemApi

/**
 * Publish a new version of a freeform canvas's React source.
 *
 * Merges into the dashboard row's `meta` (never replaces it), so existing
 * keys like `channelId`/`templateId` survive. Appends a full-file version
 * snapshot and points `currentVersionId` at it — the server-side mirror of
 * the app's dashboardsService.saveFreeform, including the linear-discard of
 * any redo tail left behind by an undo. When the publisher passes
 * `expected_current_version_id`, a publish based on a stale version is
 * rejected with 409 `version_conflict` instead of overwriting the newer head.
 */
export const DesktopFileSystemCanvasPartialUpdateBody = PatchedCanvasPublishApi

/**
 * Set or clear the Task associated with this folder's CONTEXT.md generation.
 */
export const DesktopFileSystemContextGenerationUpdateBody = ContextGenerationSetApi

/**
 * Get count of all files in a folder.
 */
export const DesktopFileSystemCountCreateBody = FileSystemApi

/**
 * Publish a new version of the folder's instructions.
 */
export const DesktopFileSystemInstructionsUpdateBody = FolderInstructionsPublishApi

/**
 * Publish a new version of the folder's instructions.
 */
export const DesktopFileSystemInstructionsPartialUpdateBody = PatchedFolderInstructionsPublishApi

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const DesktopFileSystemLinkCreateBody = FileSystemApi

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const DesktopFileSystemMoveCreateBody = FileSystemApi

/**
 * Get count of all files in a folder.
 */
export const DesktopFileSystemCountByPathCreateBody = FileSystemApi

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const DesktopFileSystemLogViewCreateBody = FileSystemApi

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const DesktopFileSystemUndoDeleteCreateBody = FileSystemApi

/**
 * Sidebar shortcuts for the desktop product surface. Reuses all FileSystemShortcutViewSet
 * behaviour but is scoped to the "desktop" surface, so its shortcuts are fully isolated from
 * the default "web" surface.
 */
export const DesktopFileSystemShortcutCreateBody = FileSystemShortcutApi

/**
 * Sidebar shortcuts for the desktop product surface. Reuses all FileSystemShortcutViewSet
 * behaviour but is scoped to the "desktop" surface, so its shortcuts are fully isolated from
 * the default "web" surface.
 */
export const DesktopFileSystemShortcutUpdateBody = FileSystemShortcutApi

/**
 * Sidebar shortcuts for the desktop product surface. Reuses all FileSystemShortcutViewSet
 * behaviour but is scoped to the "desktop" surface, so its shortcuts are fully isolated from
 * the default "web" surface.
 */
export const DesktopFileSystemShortcutPartialUpdateBody = PatchedFileSystemShortcutApi

/**
 * Set the display order of the current user's shortcuts. `ordered_ids` becomes the new top-to-bottom order; any unknown IDs are rejected.
 */
export const DesktopFileSystemShortcutReorderCreateBody = FileSystemShortcutReorderApi

export const ExportsCreateBody = ExportedAssetApi

export const FileSystemCreateBody = FileSystemApi

export const FileSystemUpdateBody = FileSystemApi

export const FileSystemPartialUpdateBody = PatchedFileSystemApi

/**
 * Get count of all files in a folder.
 */
export const FileSystemCountCreateBody = FileSystemApi

export const FileSystemLinkCreateBody = FileSystemApi

export const FileSystemMoveCreateBody = FileSystemApi

/**
 * Get count of all files in a folder.
 */
export const FileSystemCountByPathCreateBody = FileSystemApi

export const FileSystemLogViewCreateBody = FileSystemApi

export const FileSystemUndoDeleteCreateBody = FileSystemApi

export const FileSystemShortcutCreateBody = FileSystemShortcutApi

export const FileSystemShortcutUpdateBody = FileSystemShortcutApi

export const FileSystemShortcutPartialUpdateBody = PatchedFileSystemShortcutApi

/**
 * Set the display order of the current user's shortcuts. `ordered_ids` becomes the new top-to-bottom order; any unknown IDs are rejected.
 */
export const FileSystemShortcutReorderCreateBody = FileSystemShortcutReorderApi

/**
 * Create a new password for the sharing configuration.
 */
export const InsightsSharingPasswordsCreateBody = SharingConfigurationApi

export const InsightsSharingRefreshCreateBody = SharingConfigurationApi

/**
 * Create a new password for the sharing configuration.
 */
export const NotebooksSharingPasswordsCreateBody = SharingConfigurationApi

export const NotebooksSharingRefreshCreateBody = SharingConfigurationApi

export const ProductEnablementCreateBody = ProductEnablementApi

export const ProjectSecretApiKeysCreateBody = ProjectSecretAPIKeyApi

export const ProjectSecretApiKeysUpdateBody = ProjectSecretAPIKeyApi

export const ProjectSecretApiKeysPartialUpdateBody = PatchedProjectSecretAPIKeyApi

export const PropertyDefinitionsUpdateBody = EnterprisePropertyDefinitionApi

export const PropertyDefinitionsPartialUpdateBody = PatchedEnterprisePropertyDefinitionApi

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
export const PropertyDefinitionsBulkUpdateTagsCreateBody = BulkUpdateTagsRequestApi

/**
 * Create a new password for the sharing configuration.
 */
export const SessionRecordingsSharingPasswordsCreateBody = SharingConfigurationApi

export const SessionRecordingsSharingRefreshCreateBody = SharingConfigurationApi

/**
 * Replace the authenticated user's profile and settings. Pass `@me` as the UUID to update the authenticated user. Prefer the PATCH endpoint for partial updates — PUT requires every writable field to be provided.
 */
export const UsersUpdateBody = UserApi

/**
 * Update one or more of the authenticated user's profile fields or settings.
 */
export const UsersPartialUpdateBody = PatchedUserApi

export const UsersHedgehogConfigPartialUpdateBody = PatchedUserApi

/**
 * Seed personal GitHub manage callback state before opening installation settings on GitHub.
 */
export const UsersIntegrationsGithubPrepareCallbackCreateBody = UserGitHubPrepareCallbackRequestApi

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
export const UsersIntegrationsGithubStartCreateBody = UserGitHubLinkStartRequestApi

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
export const UsersIntegrationsSlackStartCreateBody = UserSlackLinkStartRequestApi

/**
 * Mark the current user as having exited onboarding with a non-delegated reason.
 * Idempotent: the skip timestamp is only set on the first successful call.
 *
 * Callers wanting to delegate setup to a teammate must use the dedicated
 * /organizations/{id}/invites/delegate/ endpoint, which atomically creates the
 * invite and sets reason="delegated". This endpoint rejects that reason so state
 * can't be faked without a real invite.
 */
export const UsersOnboardingSkipCreateBody = OnboardingSkipRequestApi

/**
 * Idempotent upsert: if the (user, token) pair already exists, `platform` and `last_seen_at` are refreshed. Otherwise a new row is created.
 * @summary Register a push notification token
 */
export const UsersPushTokensCreateBody = UserPushTokenRegisterRequestApi

/**
 * Delete the row matching `(user, token)`. Returns 204 even if no row matches so the mobile client can call this unconditionally when the user opts out.
 * @summary Unregister a push notification token
 */
export const UsersPushTokensUnregisterCreateBody = UserPushTokenUnregisterRequestApi

export const UsersScenePersonalisationCreateBody = UserApi

/**
 * Generate new backup codes, invalidating any existing ones
 */
export const UsersTwoFactorBackupCodesCreateBody = UserApi

/**
 * Disable 2FA and remove all related devices
 */
export const UsersTwoFactorDisableCreateBody = UserApi

export const UsersTwoFactorValidateCreateBody = UserApi

export const UsersValidate2faCreateBody = UserApi

export const UsersCancelEmailChangeRequestPartialUpdateBody = PatchedUserApi

export const UsersRequestEmailVerificationCreateBody = UserApi

export const UsersVerifyEmailCreateBody = UserApi
