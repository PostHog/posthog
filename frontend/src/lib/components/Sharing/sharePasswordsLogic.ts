import { actions, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { SharePasswordType } from '~/types'

import type { sharePasswordsLogicType } from './sharePasswordsLogicType'

export interface SharePasswordsLogicProps {
    dashboardId?: number
    insightId?: number
    recordingId?: string
}

export const sharePasswordsLogic = kea<sharePasswordsLogicType>([
    path(['lib', 'components', 'Sharing', 'sharePasswordsLogic']),
    props({} as SharePasswordsLogicProps),
    key(
        ({ dashboardId, insightId, recordingId }) =>
            `${dashboardId || 'no-dashboard'}-${insightId || 'no-insight'}-${recordingId || 'no-recording'}`
    ),

    actions({
        setNewPasswordModalOpen: (open: boolean) => ({ open }),
        createPassword: (password?: string, note?: string) => ({ password, note }),
        createPasswordSuccess: (response: any) => ({ response }),
        createPasswordFailure: (error: any) => ({ error }),
        deletePassword: (passwordId: string) => ({ passwordId }),
        setSharePasswords: (passwords: SharePasswordType[]) => ({ passwords }),
        loadSharePasswords: true,
        clearCreatedPasswordResult: true,
    }),

    loaders(({ props }) => ({
        sharePasswords: {
            __default: [] as SharePasswordType[],
            loadSharePasswords: async (): Promise<SharePasswordType[]> => {
                const response = await api.sharing.get({
                    dashboardId: props.dashboardId,
                    insightId: props.insightId,
                    recordingId: props.recordingId,
                })
                return (response && (response as any).share_passwords) || []
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
                        insightId: props.insightId,
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

                // Return void - response is already stored in createPasswordSuccess
            } catch (error: any) {
                console.error('Password creation error:', error)
                actions.createPasswordFailure(error)
                lemonToast.error(error.detail || error.message || 'Failed to create password')
            }
        },

        deletePassword: async ({ passwordId }) => {
            try {
                await api.sharing.deletePassword(
                    {
                        dashboardId: props.dashboardId,
                        insightId: props.insightId,
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
