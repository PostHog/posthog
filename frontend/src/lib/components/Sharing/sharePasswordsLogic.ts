import { actions, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import type { sharePasswordsLogicType } from './sharePasswordsLogicType'

export interface SharePassword {
    id: string
    created_at: string
    note: string
    created_by_email: string
    is_active: boolean
}

export interface SharePasswordsLogicProps {
    dashboardId?: number
    insightShortId?: string
    recordingId?: string
}

export const sharePasswordsLogic = kea<sharePasswordsLogicType>([
    path(['lib', 'components', 'Sharing', 'sharePasswordsLogic']),
    props({} as SharePasswordsLogicProps),
    key(
        ({ dashboardId, insightShortId, recordingId }) =>
            `${dashboardId || 'no-dashboard'}-${insightShortId || 'no-insight'}-${recordingId || 'no-recording'}`
    ),

    actions({
        setNewPasswordModalOpen: (open: boolean) => ({ open }),
        createPassword: (password?: string, note?: string) => ({ password, note }),
        createPasswordSuccess: (response: any) => ({ response }),
        createPasswordFailure: (error: any) => ({ error }),
        deletePassword: (passwordId: string) => ({ passwordId }),
        setSharePasswords: (passwords: SharePassword[]) => ({ passwords }),
        loadSharePasswords: true,
        clearCreatedPasswordResult: true,
    }),

    loaders(({ props }) => ({
        sharePasswords: {
            __default: [] as SharePassword[],
            loadSharePasswords: async (): Promise<SharePassword[]> => {
                const response = await api.sharing.get({
                    dashboardId: props.dashboardId,
                    insightId: props.insightShortId,
                    recordingId: props.recordingId,
                })
                return (response && response.share_passwords) || []
            },
        },
    })),

    reducers({
        newPasswordModalOpen: [
            false,
            {
                setNewPasswordModalOpen: (_, { open }) => open,
            },
        ],
        isCreatingPassword: [
            false as boolean,
            {
                createPassword: () => true,
                createPasswordSuccess: () => false,
                createPasswordFailure: () => false,
            },
        ],
        createdPasswordResult: [
            null as { id: string; password: string; note: string; created_at: string; created_by_email: string } | null,
            {
                createPasswordSuccess: (_, { response }) => response,
                createPassword: () => null,
                createPasswordFailure: () => null,
                clearCreatedPasswordResult: () => null,
            },
        ],
    }),

    listeners(({ actions, props }) => ({
        createPassword: async ({ password, note }) => {
            try {
                const response = await api.sharing.createPassword(
                    {
                        dashboardId: props.dashboardId,
                        insightId: props.insightShortId,
                        recordingId: props.recordingId,
                    },
                    {
                        raw_password: password,
                        note: note,
                    }
                )

                actions.createPasswordSuccess(response)
                lemonToast.success('Password created successfully')

                // Reload passwords list (but don't let this failure affect the success)
                try {
                    actions.loadSharePasswords()
                } catch (loadError) {
                    console.warn('Failed to reload passwords after creation:', loadError)
                }

                return response
            } catch (error: any) {
                console.error('Password creation error:', error)
                actions.createPasswordFailure()
                lemonToast.error(error.detail || error.message || 'Failed to create password')
                throw error
            }
        },

        deletePassword: async ({ passwordId }) => {
            try {
                await api.sharing.deletePassword(
                    {
                        dashboardId: props.dashboardId,
                        insightId: props.insightShortId,
                        recordingId: props.recordingId,
                    },
                    passwordId
                )

                actions.loadSharePasswords()
                lemonToast.success('Password deleted')
            } catch (error: any) {
                lemonToast.error(error.detail || 'Failed to delete password')
            }
        },
    })),
])
