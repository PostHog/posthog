import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
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
        deletePassword: (passwordId: string) => ({ passwordId }),
        setSharePasswords: (passwords: SharePassword[]) => ({ passwords }),
    }),

    loaders(({ props }) => ({
        sharePasswords: {
            __default: [] as SharePassword[],
            loadSharePasswords: async (): Promise<SharePassword[]> => {
                const params = new URLSearchParams()
                if (props.dashboardId) {
                    params.append('dashboard_id', props.dashboardId.toString())
                }
                if (props.insightShortId) {
                    params.append('insight_id', props.insightShortId)
                }
                if (props.recordingId) {
                    params.append('recording_id', props.recordingId)
                }

                const response = await api.get(`api/projects/@current/sharing_configurations/?${params.toString()}`)
                return response.share_passwords || []
            },
        },
        isCreatingPassword: [
            false,
            {
                createPassword: () => true,
                createPasswordSuccess: () => false,
                createPasswordFailure: () => false,
            },
        ],
    })),

    reducers({
        newPasswordModalOpen: [
            false,
            {
                setNewPasswordModalOpen: (_, { open }) => open,
            },
        ],
    }),

    listeners(({ actions, props }) => ({
        createPassword: async ({ password, note }) => {
            try {
                const params = new URLSearchParams()
                if (props.dashboardId) {
                    params.append('dashboard_id', props.dashboardId.toString())
                }
                if (props.insightShortId) {
                    params.append('insight_id', props.insightShortId)
                }
                if (props.recordingId) {
                    params.append('recording_id', props.recordingId)
                }

                const payload: Record<string, string> = {}
                if (password) {
                    payload.raw_password = password
                }
                if (note) {
                    payload.note = note
                }

                const response = await api.create(
                    `api/projects/@current/sharing_configurations/passwords/?${params.toString()}`,
                    payload
                )

                actions.createPasswordSuccess()
                actions.loadSharePasswords()
                lemonToast.success('Password created successfully')
                return response
            } catch (error: any) {
                actions.createPasswordFailure()
                lemonToast.error(error.detail || 'Failed to create password')
                throw error
            }
        },

        deletePassword: async ({ passwordId }) => {
            try {
                const params = new URLSearchParams()
                if (props.dashboardId) {
                    params.append('dashboard_id', props.dashboardId.toString())
                }
                if (props.insightShortId) {
                    params.append('insight_id', props.insightShortId)
                }
                if (props.recordingId) {
                    params.append('recording_id', props.recordingId)
                }

                await api.delete(
                    `api/projects/@current/sharing_configurations/passwords/${passwordId}/?${params.toString()}`
                )

                actions.loadSharePasswords()
                lemonToast.success('Password deleted')
            } catch (error: any) {
                lemonToast.error(error.detail || 'Failed to delete password')
            }
        },
    })),

    selectors({
        sharePasswordsLoading: [(s) => [s.sharePasswordsLoading], (loading) => loading],
    }),
])
