import { actions, kea, key, listeners, path, props, selectors } from 'kea'

import { AccessControlResourceType } from '~/types'

import type { ingestionControlsLogicType } from './ingestionControlsLogicType'

export type IngestionControlsLogicProps = {
    logicKey: string
    resourceType: AccessControlResourceType
    matchType: 'any' | 'all'
    onChangeMatchType: (matchType: 'any' | 'all') => void
}

export const ingestionControlsLogic = kea<ingestionControlsLogicType>([
    props({} as IngestionControlsLogicProps),
    key((props) => props.logicKey),
    path((key) => ['lib', 'components', 'IngestionControls', 'ingestionControlsLogic', key]),
    actions({
        onChangeMatchType: (matchType: 'any' | 'all') => ({ matchType }),
    }),
    selectors({
        logicKey: [(_, p) => [p.logicKey], (logicKey) => logicKey],
        resourceType: [(_, p) => [p.resourceType], (resourceType) => resourceType],
        matchType: [(_, p) => [p.matchType], (matchType) => matchType],
    }),
    listeners(({ props }) => ({
        onChangeMatchType: ({ matchType }) => {
            props.onChangeMatchType(matchType)
        },
    })),
])
