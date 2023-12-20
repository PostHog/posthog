import { actions, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { propertyFilterTypeToPropertyDefinitionType } from 'lib/components/PropertyFilters/utils'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { InsightLogicProps } from '~/types'

import type { breakdownTagLogicType } from './breakdownTagLogicType'
import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'
import { isURLNormalizeable } from './taxonomicBreakdownFilterUtils'

export interface BreakdownTagLogicProps {
    insightProps: InsightLogicProps
    breakdown: string | number
    breakdownType: string
    isTrends: boolean
}

export const breakdownTagLogic = kea<breakdownTagLogicType>([
    props({} as BreakdownTagLogicProps),
    key(({ insightProps, breakdown }) => `${keyForInsightLogicProps('new')(insightProps)}-${breakdown}`),
    path((key) => ['scenes', 'insights', 'BreakdownFilter', 'breakdownTagLogic', key]),
    connect(() => ({
        values: [propertyDefinitionsModel, ['getPropertyDefinition'], cohortsModel, ['cohortsById']],
        actions: [taxonomicBreakdownFilterLogic, ['removeBreakdown as removeBreakdownFromList']],
    })),
    actions(() => ({
        removeBreakdown: true,
    })),
    selectors({
        propertyDefinition: [
            (s, p) => [s.getPropertyDefinition, p.breakdown, p.breakdownType],
            (getPropertyDefinition, breakdown, breakdownType) =>
                getPropertyDefinition(breakdown, propertyFilterTypeToPropertyDefinitionType(breakdownType)),
        ],
        isHistogramable: [
            (s, p) => [p.isTrends, s.propertyDefinition],
            (isTrends, propertyDefinition) => isTrends && !!propertyDefinition?.is_numerical,
        ],
        isNormalizeable: [
            (s) => [s.propertyDefinition],
            (propertyDefinition) => isURLNormalizeable(propertyDefinition?.name || ''),
        ],
    }),
    listeners(({ props, actions }) => ({
        removeBreakdown: () => {
            actions.removeBreakdownFromList(props.breakdown)
        },
    })),
])
