import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { objectsEqual } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'

import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { Node } from '~/queries/schema'
import { InsightLogicProps } from '~/types'

import { insightLogic } from './insightLogic'
import { insightSceneLogic } from './insightSceneLogic'
import type { insightUsageLogicType } from './insightUsageLogicType'
import { keyForInsightLogicProps } from './sharedUtils'

const IS_TEST_MODE = process.env.NODE_ENV === 'test'

export const insightUsageLogic = kea<insightUsageLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'insightUsageLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [
            insightLogic(props),
            ['insight'],
            dataNodeLogic({ key: insightVizDataNodeKey(props) } as DataNodeLogicProps),
            ['query'],
        ],
        actions: [eventUsageLogic, ['reportInsightViewed']],
    })),
    actions({
        onQueryChange: (query: Node | null, previousQuery?: Node | null) => ({
            query,
            previousQuery,
        }),
        setNotFirstLoad: true,
    }),
    reducers({
        isFirstLoad: [
            true,
            {
                setNotFirstLoad: () => false,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        onQueryChange: async ({ query }, breakpoint) => {
            // We only want to report direct views on the insights page.
            if (
                !insightSceneLogic.isMounted() ||
                insightSceneLogic.values.activeScene !== 'Insight' ||
                insightSceneLogic.values.insight?.short_id !== values.insight?.short_id
            ) {
                return
            }

            // Report the insight being viewed to our '/viewed' endpoint. Used for "recently viewed insights".
            if (values.insight.id) {
                void api.create(`api/projects/${teamLogic.values.currentTeamId}/insights/${values.insight.id}/viewed`)
            }

            // Debounce to avoid noisy events from the query changing multiple times.
            await breakpoint(IS_TEST_MODE ? 1 : 500)

            actions.reportInsightViewed(values.insight, query, values.isFirstLoad, 0)
            actions.setNotFirstLoad()

            // Record a second view after 10 seconds.
            await breakpoint(IS_TEST_MODE ? 1 : 10000)

            actions.reportInsightViewed(values.insight, query, values.isFirstLoad, 10)
        },
    })),
    subscriptions(({ actions }) => ({
        query: (query, oldQuery) => {
            if (objectsEqual(query, oldQuery)) {
                return
            }
            actions.onQueryChange(query, oldQuery)
        },
    })),
])
