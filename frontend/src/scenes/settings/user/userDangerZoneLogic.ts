import { kea } from 'kea'
import { router } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { urls } from 'scenes/urls'

import type { OrganizationBasicType } from '~/types'

import type { userDangerZoneLogicType } from './userDangerZoneLogicType'

export const userDangerZoneLogic = kea<userDangerZoneLogicType>({
    path: ['scenes', 'settings', 'user', 'userDangerZoneLogic'],
    actions: {
        setDeleteUserModalOpen: (open: boolean) => ({ open }),
        setOrganizationToDelete: (organization: OrganizationBasicType | null) => ({ organization }),
        setIsUserDeletionConfirmed: (confirmed: boolean) => ({ confirmed }),
    },
    loaders: {
        _leaveOrganization: [
            null,
            {
                leaveOrganization: async (organizationId: string) => {
                    await api.delete(`api/organizations/${organizationId}/members/@me/`)

                    return null
                },
            },
        ],
    },
    reducers: {
        deleteUserModalOpen: [
            false,
            {
                setDeleteUserModalOpen: (_, { open }) => open,
            },
        ],
        organizationToDelete: [
            null as OrganizationBasicType | null,
            {
                setOrganizationToDelete: (_, { organization }) => organization,
            },
        ],
        isUserDeletionConfirmed: [
            false,
            {
                setIsUserDeletionConfirmed: (_, { confirmed }) => confirmed,
            },
        ],
    },
    listeners: () => ({
        setDeleteUserModalOpen: ({ open }) => {
            if (open) {
                router.actions.replace(urls.settings('user-danger-zone'), { deletingUser: true })
            } else {
                router.actions.replace(urls.settings('user-danger-zone'))
            }
        },
        leaveOrganizationSuccess: () => {
            router.actions.replace(urls.settings('user-danger-zone'), { deletingUser: true })

            lemonToast.success('Organization left successfully')

            window.location.reload()
        },
        leaveOrganizationFailure: () => {
            lemonToast.error('Failed to leave organization')
        },
    }),
    urlToAction: ({ actions, values }) => ({
        [urls.settings('user-danger-zone')]: (_, searchParams) => {
            const { deletingUser } = searchParams
            if (deletingUser && !values.deleteUserModalOpen) {
                actions.setDeleteUserModalOpen(true)
            }
        },
    }),
})
