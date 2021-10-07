import { kea } from 'kea'
import { insightMetadataLogicType } from './insightMetadataLogicType'
import { AvailableFeature, DashboardItemType } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { cleanMetadataValues } from 'scenes/insights/InsightMetadata/utils'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export interface InsightMetadataLogicProps {
    insight?: Partial<DashboardItemType>
}

export const insightMetadataLogic = kea<insightMetadataLogicType<InsightMetadataLogicProps>>({
    props: {} as InsightMetadataLogicProps,
    actions: {
        setInsightMetadata: (insight: Partial<DashboardItemType>) => ({ insight }),
        saveInsightMetadata: (property: keyof DashboardItemType, shouldPersist: boolean = false) => ({
            property,
            shouldPersist,
        }),
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
    selectors: {
        isEditable: [
            () => [featureFlagLogic.selectors.featureFlags, userLogic.selectors.user],
            (ff, user) => {
                return (
                    ff[FEATURE_FLAGS.SAVED_INSIGHTS] &&
                    user?.organization?.available_features?.includes(AvailableFeature.DASHBOARD_COLLABORATION)
                )
            },
        ],
    },
    listeners: ({ values, actions }) => ({
        saveInsightMetadata: async ({ property, shouldPersist }, breakpoint) => {
            await breakpoint(200)
            if (shouldPersist) {
                // Persists insight metadata by directly making the update api call
                await actions.updateInsight({ [property]: values.insightMetadata[property] })
            } else {
                // Update local insight state
                await actions.setInsight({ [property]: values.insightMetadata[property] }, true)
            }
            actions.setInsightMetadata({ [property]: values.insightMetadata[property] }) // sync
            actions.showViewMode(property)
        },
        cancelInsightMetadata: async ({ property }) => {
            await actions.setInsightMetadata({ [property]: undefined })
            actions.showViewMode(property)
        },
    }),
})
