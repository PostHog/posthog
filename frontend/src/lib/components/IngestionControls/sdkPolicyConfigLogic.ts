import { kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { AccessControlResourceType } from '~/types'

import type { sdkPolicyConfigLogicType } from './sdkPolicyConfigLogicType'

export type IngestionControlsLogicProps = {
    logicKey: string
    resourceType: AccessControlResourceType | null
    matchType: 'any' | 'all'
    onChangeMatchType: (matchType: 'any' | 'all') => void
}

export const sdkPolicyConfigLogic = kea<sdkPolicyConfigLogicType>([
    path(['lib', 'components', 'IngestionControls', 'sdkPolicyConfigLogic']),
    loaders({
        config: [
            null as any | null,
            {
                loadConfig: async () => {
                    return await api.errorTracking.sdkPolicyConfig.get()
                },
            },
        ],
    }),
])
