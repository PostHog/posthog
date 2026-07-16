import { kea, key, path, props } from 'kea'
import { lazyLoaders } from 'kea-loaders'

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
                    return await getPersonMessageAssets(props.teamId, props.personId)
                },
            },
        ],
    })),
])
