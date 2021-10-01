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
        saveInsightMetadata: (property: keyof DashboardItemType) => ({ property }),
        showEditMode: (property: keyof DashboardItemType) => ({ property }),
        showViewMode: (property: keyof DashboardItemType) => ({ property }),
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
            console.log('SAVE', values.insightMetadata)
            await actions.setInsight(values.insightMetadata, true)
            actions.showViewMode(property)
        },
    }),
})
