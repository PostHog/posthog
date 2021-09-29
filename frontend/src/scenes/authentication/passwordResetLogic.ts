import { kea } from 'kea'
import api from 'lib/api'
import { passwordResetLogicType } from './passwordResetLogicType'

interface ResetResponseType {
    success: boolean
    errorCode?: string
    errorDetail?: string
    email?: string
}

export const passwordResetLogic = kea<passwordResetLogicType<ResetResponseType>>({
    loaders: {
        resetResponse: [
            null as ResetResponseType | null,
            {
                reset: async ({ email }: { email: string }) => {
                    return { success: false, errorCode: 'error', errorDetail: 'Requests limit exceeded' }
                    try {
                        await api.create('api/reset', { email })
                        return { success: true, email }
                    } catch (e) {
                        return { success: false, errorCode: e.code, errorDetail: e.detail }
                    }
                },
            },
        ],
    },
})
