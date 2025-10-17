import { actions, kea, path, reducers } from 'kea'

import type { nuxtInstructionsLogicType } from './nuxtInstructionsLogicType'

export type NuxtVersion = 'v3.7+' | 'v3.6-'

export interface NuxtInstructionsLogicProps {
    initialVersion?: NuxtVersion
}

export const nuxtInstructionsLogic = kea<nuxtInstructionsLogicType>([
    path(['scenes', 'onboarding', 'sdks', 'error-tracking', 'nuxtInstructionsLogic']),
    actions({
        setNuxtVersion: (version) => ({ version }),
    }),
    reducers(({ props }) => ({
        nuxtVersion: [
            (props.initialVersion || 'v3.7+') as NuxtVersion,
            {
                setNuxtVersion: (_, { version }) => version,
            },
        ],
    })),
])
