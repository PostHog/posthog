import { actions, kea, key, path, props, selectors } from 'kea'
import { listeners } from 'process'

import { AccessControlResourceType } from '~/types'

import type { ingestionTriggersLogicType } from './ingestionTriggersLogicType'

export type IngestionTriggersLogicProps = {
    logicKey: string
    resourceType: AccessControlResourceType
    matchType: 'any' | 'all'
    onChangeMatchType: (matchType: 'any' | 'all') => void
}

export const ingestionTriggersLogic = kea<ingestionTriggersLogicType>([
    props({} as IngestionTriggersLogicProps),
    key((props) => props.logicKey),
    path((key) => ['lib', 'components', 'IngestionTriggers', 'ingestionTriggersLogic', key]),
    actions({
        onChangeMatchType: (matchType: 'any' | 'all') => ({ matchType }),
    }),
    selectors({
        resourceType: [(_, p) => [p.resourceType], (resourceType) => resourceType],
        matchType: [(_, p) => [p.matchType], (matchType) => matchType],
    }),
    listeners(({ props }) => ({
        onChangeMatchType: ({ matchType }) => {
            props.onChangeMatchType(matchType)
        },
    })),
])
