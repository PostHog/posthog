import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { lazyLoaders, loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import api, { PaginatedResponse } from 'lib/api'
import { OrganizationMembershipLevel } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { organizationLogic } from 'scenes/organizationLogic'

import { ActivationTask, activationLogic } from '~/layout/navigation-3000/sidepanel/panels/activation/activationLogic'
import { AccessControlLevel, OrganizationInviteType } from '~/types'

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
        values: [preflightLogic, ['preflight']],
        actions: [router, ['locationChanged']],
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
                        'api/organizations/@current/invites/bulk/',
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
                                  'api/organizations/@current/invites/'
                              )
                          ).results
                        : []
                },
                deleteInvite: async (invite: OrganizationInviteType) => {
                    await api.delete(`api/organizations/@current/invites/${invite.id}/`)
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
                locationChanged: () => false,
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
        canSubmit: [
            (selectors) => [selectors.invitesToSend, selectors.inviteContainsOwnerLevel, selectors.isInviteConfirmed],
            (invites: InviteRowState[], inviteContainsOwnerLevel: boolean, isInviteConfirmed: boolean) => {
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
                lemonToast.success(`Invited ${inviteCount} new team member${inviteCount === 1 ? '' : 's'}`)
            } else {
                lemonToast.success('Team invite links generated')
            }

            organizationLogic.actions.loadCurrentOrganization()
            actions.loadInvites()

            if (values.preflight?.email_service_available) {
                actions.hideInviteModal()
            }

            if (inviteCount > 0) {
                // We want to avoid this updating the team before the onboarding is finished
                setTimeout(() => {
                    activationLogic.findMounted()?.actions?.markTaskAsCompleted(ActivationTask.InviteTeamMember)
                }, 1000)
            }
        },
        addProjectAccess: ({ projectId }) => {
            // Load access control for the project when it's added
            actions.loadProjectAccessControl(projectId)
        },
    })),
    urlToAction(({ actions }) => ({
        '*': (_, searchParams) => {
            if (searchParams.invite_modal) {
                actions.showInviteModal()
            }
        },
    })),
])
