import { actions, connect, kea, key, listeners, path, props, selectors } from 'kea'

import type { breakdownTagLogicType } from './breakdownTagLogicType'
import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'
import { isAllCohort, isCohort, isURLNormalizeable } from './taxonomicBreakdownFilterUtils'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { propertyFilterTypeToPropertyDefinitionType } from 'lib/components/PropertyFilters/utils'

export interface BreakdownTagLogicProps {
    breakdown: string | number
    breakdownType: string
    isTrends: boolean
}

export const breakdownTagLogic = kea<breakdownTagLogicType>([
    props({} as BreakdownTagLogicProps),
    key(({ breakdown }) => breakdown),
    path((key) => ['scenes', 'insights', 'BreakdownFilter', 'breakdownTagLogic', key]),
    connect(() => ({
        values: [
            taxonomicBreakdownFilterLogic,
            ['isViewOnly'],
            propertyDefinitionsModel,
            ['getPropertyDefinition'],
            cohortsModel,
            ['cohortsById'],
        ],
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
        propertyName: [
            (s, p) => [p.breakdown, s.cohortsById],
            (breakdown, cohortsById) => {
                if (isAllCohort(breakdown)) {
                    return 'All Users'
                } else if (isCohort(breakdown)) {
                    return cohortsById[breakdown]?.name || `Cohort ${breakdown}`
                } else {
                    // regular property breakdown i.e. person, event or group
                    return breakdown
                }
            },
        ],
        isHistogramable: [
            (s, p) => [p.isTrends, s.propertyDefinition],
            (isTrends, propertyDefinition) => isTrends && !!propertyDefinition?.is_numerical,
        ],
        isNormalizeable: [
            (s) => [s.propertyDefinition],
            (propertyDefinition) => isURLNormalizeable(propertyDefinition?.name || ''),
        ],
        shouldShowMenu: [
            (s) => [s.isViewOnly, s.isHistogramable, s.isNormalizeable],
            (isViewOnly, isHistogramable, isNormalizeable) => !isViewOnly && (isHistogramable || isNormalizeable),
        ],
    }),
    listeners(({ props, actions }) => ({
        removeBreakdown: () => {
            actions.removeBreakdownFromList(props.breakdown)
        },
    })),
])
