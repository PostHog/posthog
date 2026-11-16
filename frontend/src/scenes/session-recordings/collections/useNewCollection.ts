import posthog from 'posthog-js'
import { useState } from 'react'

import { isAccessDeniedError, shouldReportApiFailure } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { createPlaylist } from '../playlist/playlistUtils'

export function useNewCollection(): { createCollection: () => Promise<void>; creating: boolean } {
    const [creating, setCreating] = useState(false)
    const createCollection = async (): Promise<void> => {
        setCreating(true)
        try {
            await createPlaylist(
                { _create_in_folder: 'Unfiled/Replay playlists', type: 'collection', creation_method: 'new' },
                true
            )
        } catch (error: any) {
            if (isAccessDeniedError(error)) {
                lemonToast.error('You do not have access to create collections.')
            } else {
                lemonToast.error('Could not create the collection. Please try again.')
            }
            if (shouldReportApiFailure(error)) {
                posthog.captureException(error)
            }
        } finally {
            setCreating(false)
        }
    }
    return { createCollection, creating }
}
