import { kea } from 'kea'
import { insightMetadataLogicType } from './insightMetadataLogicType'
import { DashboardItemType } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'

interface InsightMetadataLogic {
    insight?: Partial<DashboardItemType>
}

export const insightMetadataLogic = kea<insightMetadataLogicType<InsightMetadataLogic>>({
    props: {} as InsightMetadataLogic,
    actions: {
        setInsightMetadata: (insight: Partial<DashboardItemType>) => ({ insight }),
        updateInsightMetadata: (insight: Partial<DashboardItemType>) => ({ insight }),
    },
    connect: {
        actions: [insightLogic, ['setInsight', 'updateInsight']],
    },
    reducers: ({ props }) => ({
        insightMetadata: [
            props.insight ?? {},
            {
                setInsightMetadata: (state, { insight }) => ({ ...state, ...insight }),
            },
        ],
    }),
    listeners: ({ values, actions }) => ({
        setInsightMetadata: async (_, breakpoint) => {
            await breakpoint(200)
            actions.setInsight(values.insightMetadata, true)
        },
        updateInsightMetadata: ({ insight }) => {
            actions.updateInsight(insight)
        },
    }),
})
