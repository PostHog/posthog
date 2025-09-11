import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

export const openInAdminPanel = async (email: string): Promise<void> => {
    try {
        const response = await api.users.list(email)

        if (!response.results || response.results.length === 0) {
            throw new Error('User not found')
        }

        const userId = response.results[0].id
        window.open(`/admin/posthog/user/${userId}/change/`, '_blank')
    } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        lemonToast.error(`Failed to open admin panel: ${message}`)
    }
}
