import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { lazyLoaders, loaders } from 'kea-loaders'

import api, { PaginatedResponse } from 'lib/api'
import { OrganizationMembershipLevel } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { bindModalToUrl } from 'lib/logic/bindModalToUrl'
import { pluralize } from 'lib/utils'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { AccessControlLevel, OrganizationInviteType } from '~/types'

import type { inviteLogicType } from './inviteLogicType'

/** Grant the guest invite will materialize on acceptance. Mirrors one entry of
 *  `OrganizationInvite.guest_resources`. */
export interface GuestInviteGrant {
    team_id: number
    resource: 'notebook'
    resource_id: string
    /** Per-resource access level. Defaults to viewer when the admin adds a grant. */
    access_level: 'viewer' | 'editor'
    /** Display label for the UI only; not sent to the server. */
    label?: string
}

/** Shape accepted by `addGuestGrant` — access_level is optional and defaults to viewer. */
export type GuestInviteGrantInput = Omit<GuestInviteGrant, 'access_level'> & {
    access_level?: 'viewer' | 'editor'
}

/** State of a single invite row (with input data) in bulk invite creation. */
export interface InviteRowState {
    target_email: string
    first_name: string
    level: OrganizationMembershipLevel
    isValid: boolean
    message?: string
    private_project_access: Array<{ id: number; level: AccessControlLevel.Member | AccessControlLevel.Admin }>
}

const EMPTY_INVITE: InviteRowState = {
    target_email: '',
    first_name: '',
    level: OrganizationMembershipLevel.Member,
    isValid: true,
    private_project_access: [],
}

export const inviteLogic = kea<inviteLogicType>([
    path(['scenes', 'organization', 'Settings', 'inviteLogic']),
    connect(() => ({
        values: [preflightLogic, ['preflight']],
    })),
    actions({
        showInviteModal: true,
        hideInviteModal: true,
        updateInviteAtIndex: (payload, index: number) => ({ payload, index }),
        deleteInviteAtIndex: (index: number) => ({ index }),
        updateMessage: (message: string) => ({ message }),
        appendInviteRow: true,
        resetInviteRows: true,
        setIsInviteConfirmed: (inviteConfirmed: boolean) => ({ inviteConfirmed }),
        addProjectAccess: (inviteIndex: number, projectId: number, level: AccessControlLevel) => ({
            inviteIndex,
            projectId,
            level,
        }),
        removeProjectAccess: (inviteIndex: number, projectId: number) => ({ inviteIndex, projectId }),
        setIsGuestInvite: (isGuest: boolean) => ({ isGuest }),
        addGuestGrant: (grant: GuestInviteGrantInput) => ({ grant }),
        removeGuestGrant: (index: number) => ({ index }),
        setGuestGrantAccessLevel: (index: number, access_level: 'viewer' | 'editor') => ({ index, access_level }),
        setBypassSsoEnforcement: (bypass: boolean) => ({ bypass }),
        resetGuestState: true,
    }),
    loaders(({ values }) => ({
        invitedTeamMembersInternal: [
            [] as OrganizationInviteType[],
            {
                inviteTeamMembers: async () => {
                    if (!values.canSubmit) {
                        return []
                    }

                    if (values.isGuestInvite) {
                        // Guest invites are one-at-a-time; take the first filled row.
                        const firstInvite = values.invitesToSend.find((invite) => invite.target_email)
                        if (!firstInvite) {
                            return []
                        }
                        const guestPayload = {
                            target_email: firstInvite.target_email,
                            first_name: firstInvite.first_name,
                            guest_resources: values.guestGrants.map((g) => ({
                                team_id: g.team_id,
                                resource: g.resource,
                                resource_id: g.resource_id,
                                access_level: g.access_level,
                            })),
                            bypass_sso: values.bypassSsoEnforcement,
                        }
                        return await api.create<OrganizationInviteType[]>(
                            `api/organizations/${organizationLogic.values.currentOrganizationId}/invites/bulk/`,
                            [guestPayload]
                        )
                    }

                    const payload: Pick<
                        OrganizationInviteType,
                        'target_email' | 'first_name' | 'level' | 'message' | 'private_project_access'
                    >[] = values.invitesToSend.filter((invite) => invite.target_email)
                    if (values.message) {
                        payload.forEach((payload) => (payload.message = values.message))
                    }
                    return await api.create<OrganizationInviteType[]>(
                        `api/organizations/${organizationLogic.values.currentOrganizationId}/invites/bulk/`,
                        payload
                    )
                },
            },
        ],
        projectAccessControls: [
            {} as Record<number, { access_level: string }>,
            {
                loadProjectAccessControl: async (projectId: number) => {
                    try {
                        const accessControls = await api.get(`api/projects/${projectId}/access_controls`)
                        // Look for project-level access control (resource: "project", organization_member: null, role: null)
                        const projectAccessControl = accessControls.access_controls?.find(
                            (control: any) =>
                                control.resource === 'project' &&
                                control.organization_member === null &&
                                control.role === null
                        )
                        return {
                            ...values.projectAccessControls,
                            [projectId]: projectAccessControl || { access_level: accessControls.default_access_level },
                        }
                    } catch {
                        return values.projectAccessControls
                    }
                },
            },
        ],
    })),
    lazyLoaders(({ values }) => ({
        invites: [
            [] as OrganizationInviteType[],
            {
                loadInvites: async () => {
                    return organizationLogic.values.currentOrganization
                        ? (
                              await api.get<PaginatedResponse<OrganizationInviteType>>(
                                  `api/organizations/${organizationLogic.values.currentOrganizationId}/invites/`
                              )
                          ).results
                        : []
                },
                deleteInvite: async (invite: OrganizationInviteType) => {
                    await api.delete(
                        `api/organizations/${organizationLogic.values.currentOrganizationId}/invites/${invite.id}/`
                    )
                    preflightLogic.actions.loadPreflight() // Make sure licensed_users_available is updated
                    lemonToast.success(`Invite for ${invite.target_email} has been canceled`)
                    return values.invites.filter((thisInvite) => thisInvite.id !== invite.id)
                },
            },
        ],
    })),
    reducers(() => ({
        isInviteModalShown: [
            false,
            {
                showInviteModal: () => true,
                hideInviteModal: () => false,
            },
        ],
        invitesToSend: [
            [EMPTY_INVITE] as InviteRowState[],
            {
                updateInviteAtIndex: (state, { payload, index }) => {
                    const newState = [...state]
                    newState[index] = { ...state[index], ...payload }
                    return newState
                },
                deleteInviteAtIndex: (state, { index }) => {
                    const newState = [...state]
                    newState.splice(index, 1)
                    return newState
                },
                appendInviteRow: (state) => [...state, EMPTY_INVITE],
                resetInviteRows: () => [EMPTY_INVITE],
                inviteTeamMembersSuccess: () => [EMPTY_INVITE],
                addProjectAccess: (state, { inviteIndex, projectId, level }) => {
                    const newState = [...state]
                    const invite = { ...newState[inviteIndex] }

                    // Remove existing access for this project if it exists
                    invite.private_project_access = invite.private_project_access.filter(
                        (access) => access.id !== projectId
                    )

                    // Add new access
                    invite.private_project_access.push({
                        id: projectId,
                        level: level as AccessControlLevel.Member | AccessControlLevel.Admin,
                    })
                    newState[inviteIndex] = invite
                    return newState
                },
                removeProjectAccess: (state, { inviteIndex, projectId }) => {
                    const newState = [...state]
                    const invite = { ...newState[inviteIndex] }
                    invite.private_project_access = invite.private_project_access.filter(
                        (access) => access.id !== projectId
                    )
                    newState[inviteIndex] = invite
                    return newState
                },
            },
        ],
        message: [
            '',
            {
                updateMessage: (_, { message }) => message,
            },
        ],
        isInviteConfirmed: [
            false,
            {
                setIsInviteConfirmed: (_, { inviteConfirmed }) => inviteConfirmed,
            },
        ],
        isGuestInvite: [
            false,
            {
                setIsGuestInvite: (_, { isGuest }) => isGuest,
                resetGuestState: () => false,
                inviteTeamMembersSuccess: () => false,
            },
        ],
        guestGrants: [
            [] as GuestInviteGrant[],
            {
                addGuestGrant: (state, { grant }) => [
                    ...state,
                    { ...grant, access_level: grant.access_level ?? 'viewer' },
                ],
                removeGuestGrant: (state, { index }) => state.filter((_, i) => i !== index),
                setGuestGrantAccessLevel: (state, { index, access_level }) =>
                    state.map((grant, i) => (i === index ? { ...grant, access_level } : grant)),
                resetGuestState: () => [],
                inviteTeamMembersSuccess: () => [],
            },
        ],
        bypassSsoEnforcement: [
            false,
            {
                setBypassSsoEnforcement: (_, { bypass }) => bypass,
                resetGuestState: () => false,
                inviteTeamMembersSuccess: () => false,
            },
        ],
    })),
    selectors({
        inviteContainsOwnerLevel: [
            (selectors) => [selectors.invitesToSend],
            (invites: InviteRowState[]) => {
                return invites.filter(({ level }) => level === OrganizationMembershipLevel.Owner).length > 0
            },
        ],
        canSubmit: [
            (selectors) => [
                selectors.invitesToSend,
                selectors.inviteContainsOwnerLevel,
                selectors.isInviteConfirmed,
                selectors.isGuestInvite,
                selectors.guestGrants,
            ],
            (
                invites: InviteRowState[],
                inviteContainsOwnerLevel: boolean,
                isInviteConfirmed: boolean,
                isGuestInvite: boolean,
                guestGrants: GuestInviteGrant[]
            ) => {
                const validEmails = invites.filter(({ target_email, isValid }) => !!target_email && isValid)
                if (isGuestInvite) {
                    return validEmails.length === 1 && guestGrants.length > 0
                }
                const ownerLevelConfirmed = inviteContainsOwnerLevel ? isInviteConfirmed : true
                return (
                    invites.filter(({ target_email }) => !!target_email).length > 0 &&
                    invites.filter(({ isValid }) => !isValid).length == 0 &&
                    ownerLevelConfirmed
                )
            },
        ],
        availableProjects: [
            () => [organizationLogic.selectors.currentOrganization],
            (currentOrganization: any) => {
                return currentOrganization?.teams || []
            },
        ],
        isInviting: [
            (selectors) => [selectors.invitedTeamMembersInternalLoading],
            (invitedTeamMembersInternalLoading: boolean) => invitedTeamMembersInternalLoading,
        ],
    }),
    listeners(({ values, actions }) => ({
        inviteTeamMembersSuccess: (): void => {
            const inviteCount = values.invitedTeamMembersInternal.length
            if (values.preflight?.email_service_available) {
                lemonToast.success(`Invited ${pluralize(inviteCount, 'new team member')}`)
            } else {
                lemonToast.success('Team invite links generated')
            }

            organizationLogic.actions.loadCurrentOrganization()
            actions.loadInvites()
            actions.resetGuestState()

            if (values.preflight?.email_service_available) {
                actions.hideInviteModal()
            }
        },
        addProjectAccess: ({ projectId }) => {
            // Load access control for the project when it's added
            actions.loadProjectAccessControl(projectId)
        },
    })),
    bindModalToUrl({
        urlKey: 'invite-members',
        openActionKey: 'showInviteModal',
        closeActionKey: 'hideInviteModal',
        isOpenKey: 'isInviteModalShown',
    }),
])
