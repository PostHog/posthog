import { kea, key, path, props } from 'kea'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { triggersLogicType } from './triggersLogicType'

export type TriggersLogicProps = {
    logicKey: string
    resourceType: AccessControlResourceType | null
    minAccessLevel: AccessControlLevel | null
}

export const triggersLogic = kea<triggersLogicType>([
    path(['lib', 'components', 'Triggers', 'triggersLogic']),
    key((props) => props.logicKey),
    props({} as TriggersLogicProps),
])
