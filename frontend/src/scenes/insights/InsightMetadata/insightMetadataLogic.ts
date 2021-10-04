import { kea } from 'kea'
import { insightMetadataLogicType } from './insightMetadataLogicType'
import { DashboardItemType } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { cleanMetadataValues } from 'scenes/insights/InsightMetadata/utils'

export interface InsightMetadataLogicProps {
    insight?: Partial<DashboardItemType>
}

export const insightMetadataLogic = kea<insightMetadataLogicType<InsightMetadataLogicProps>>({
    props: {} as InsightMetadataLogicProps,
    actions: {
        setInsightMetadata: (insight: Partial<DashboardItemType>) => ({ insight }),
        saveInsightMetadata: (property: keyof DashboardItemType) => ({ property }),
        cancelInsightMetadata: (property: keyof DashboardItemType) => ({ property }),
        showEditMode: (property: keyof DashboardItemType) => ({ property }),
        showViewMode: (property: keyof DashboardItemType) => ({ property }),
    },
    connect: {
        actions: [insightLogic, ['setInsight', 'updateInsight']],
    },
    reducers: ({ props }) => ({
        insightMetadata: [
            cleanMetadataValues(props.insight ?? {}),
            {
                setInsightMetadata: (state, { insight }) => {
                    return { ...state, ...cleanMetadataValues(insight) }
                },
            },
        ],
        editableProps: [
            new Set(),
            {
                showEditMode: (state, { property }) => new Set([...Array.from(state), property]),
                showViewMode: (state, { property }) => new Set([...Array.from(state)].filter((p) => p !== property)),
            },
        ],
    }),
    listeners: ({ values, actions }) => ({
        saveInsightMetadata: async ({ property }, breakpoint) => {
            await breakpoint(200)

            if (!values.insightMetadata[property]) {
                return
            }

            await actions.setInsight({ [property]: values.insightMetadata[property] }, true)
            actions.showViewMode(property)
        },
        cancelInsightMetadata: async ({ property }) => {
            await actions.setInsightMetadata({ [property]: undefined })
            actions.showViewMode(property)
        },
    }),
})
