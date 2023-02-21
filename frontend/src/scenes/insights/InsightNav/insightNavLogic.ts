import { actions, kea, key, path, props } from 'kea'
import { InsightLogicProps, InsightType } from '~/types'

import type { insightNavLogicType } from './insightNavLogicType'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

export const insightNavLogic = kea<insightNavLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'InsightNav', 'insightNavLogic', key]),
    actions({
        setActiveView: (view: InsightType) => ({ view }),
    }),
])
