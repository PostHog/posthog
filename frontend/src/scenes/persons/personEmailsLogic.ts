import { kea, key, path, props } from 'kea'
import { lazyLoaders } from 'kea-loaders'

import { ApiError } from 'lib/api'

import { getPersonMessageAssets, MessageAsset } from 'products/workflows/frontend/Workflows/messageAssetsApi'

import type { personEmailsLogicType } from './personEmailsLogicType'

export interface PersonEmailsLogicProps {
    teamId: number
    personId: string
}

export const personEmailsLogic = kea<personEmailsLogicType>([
    path(['scenes', 'persons', 'personEmailsLogic']),
    props({} as PersonEmailsLogicProps),
    key((props) => `${props.teamId}-${props.personId}`),
    lazyLoaders(({ props }) => ({
        emails: [
            [] as MessageAsset[],
            {
                loadEmails: async () => {
                    if (!props.personId) {
                        return []
                    }
                    try {
                        return await getPersonMessageAssets(props.teamId, props.personId)
                    } catch (error) {
                        // A profile can render from event data while its UUID no longer resolves to a
                        // Postgres person row (deleted, merged, or split), so the emails endpoint 404s.
                        // Fall back to the empty state rather than surfacing an uncaught error.
                        if (error instanceof ApiError && error.status === 404) {
                            return []
                        }
                        throw error
                    }
                },
            },
        ],
    })),
])
