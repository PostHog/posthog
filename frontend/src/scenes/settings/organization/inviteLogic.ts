import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { lazyLoaders, loaders } from 'kea-loaders'

import api, { PaginatedResponse } from 'lib/api'
import { OrganizationMembershipLevel } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { bindModalToUrl } from 'lib/logic/bindModalToUrl'
import { pluralize } from 'lib/utils'
import { membersLogic } from 'scenes/organization/membersLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { AccessControlLevel, OrganizationInviteType, OrganizationMemberType, UserType } from '~/types'

import type { inviteLogicType } from './inviteLogicType'

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
        values: [preflightLogic, ['preflight'], userLogic, ['user'], membersLogic, ['members']],
        actions: [membersLogic, ['ensureAllMembersLoaded']],
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
    }),
    loaders(({ values }) => ({
        invitedTeamMembersInternal: [
            [] as OrganizationInviteType[],
            {
                inviteTeamMembers: async () => {
                    if (!values.canSubmit) {
                        return []
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
    })),
    selectors({
        inviteContainsOwnerLevel: [
            (selectors) => [selectors.invitesToSend],
            (invites: InviteRowState[]) => {
                return invites.filter(({ level }) => level === OrganizationMembershipLevel.Owner).length > 0
            },
        ],
        existingOrgEmails: [
            (selectors) => [selectors.user, selectors.members],
            (user: UserType | null, members: OrganizationMemberType[] | null): Set<string> => {
                const emails = new Set<string>()
                if (user?.email) {
                    emails.add(user.email.toLowerCase())
                }
                for (const member of members ?? []) {
                    if (member.user?.email) {
                        emails.add(member.user.email.toLowerCase())
                    }
                }
                return emails
            },
        ],
        inviteRowDuplicates: [
            (selectors) => [selectors.invitesToSend, selectors.existingOrgEmails, selectors.user],
            (
                invites: InviteRowState[],
                existingOrgEmails: Set<string>,
                user: UserType | null
            ): (null | 'self' | 'member')[] => {
                const ownEmail = user?.email?.toLowerCase()
                return invites.map((invite) => {
                    const email = invite.target_email?.trim().toLowerCase()
                    if (!email) {
                        return null
                    }
                    if (ownEmail && email === ownEmail) {
                        return 'self'
                    }
                    if (existingOrgEmails.has(email)) {
                        return 'member'
                    }
                    return null
                })
            },
        ],
        hasDuplicateInviteRow: [
            (selectors) => [selectors.inviteRowDuplicates],
            (duplicates: (null | 'self' | 'member')[]) => duplicates.some((d) => d !== null),
        ],
        canSubmit: [
            (selectors) => [
                selectors.invitesToSend,
                selectors.inviteContainsOwnerLevel,
                selectors.isInviteConfirmed,
                selectors.hasDuplicateInviteRow,
            ],
            (
                invites: InviteRowState[],
                inviteContainsOwnerLevel: boolean,
                isInviteConfirmed: boolean,
                hasDuplicateInviteRow: boolean
            ) => {
                const ownerLevelConfirmed = inviteContainsOwnerLevel ? isInviteConfirmed : true
                return (
                    invites.filter(({ target_email }) => !!target_email).length > 0 &&
                    invites.filter(({ isValid }) => !isValid).length == 0 &&
                    !hasDuplicateInviteRow &&
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
        showInviteModal: () => {
            // Load org members so we can flag rows that would be rejected server-side
            // ("A user with this email address already belongs to the organization.")
            // before the user submits and sees a confusing red toast.
            actions.ensureAllMembersLoaded()
        },
        inviteTeamMembersSuccess: (): void => {
            const inviteCount = values.invitedTeamMembersInternal.length
            if (values.preflight?.email_service_available) {
                lemonToast.success(`Invited ${pluralize(inviteCount, 'new team member')}`)
            } else {
                lemonToast.success('Team invite links generated')
            }

            organizationLogic.actions.loadCurrentOrganization()
            actions.loadInvites()

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
    afterMount(({ actions }) => {
        // Eagerly load org members so the duplicate-email guard has data to check
        // against in both the settings modal and onboarding flow. membersLogic is
        // permanentlyMount()'d, so this is idempotent across remounts.
        actions.ensureAllMembersLoaded()
    }),
])
