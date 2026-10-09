import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { BehavioralFilterKey } from 'scenes/cohorts/CohortFilters/types'
import { isCohortCriteriaGroup } from 'scenes/cohorts/cohortUtils'
import { FEATURE_FLAG_CALLED_EVENT } from 'scenes/feature-flags/featureFlagUsageQueries'

import { Node } from '~/queries/schema/schema-general'
import {
    isEventsNode,
    isFunnelsQuery,
    isGroupNode,
    isInsightQueryWithSeries,
    isInsightVizNode,
    isRetentionQuery,
} from '~/queries/utils'
import {
    ActionType,
    AnyCohortCriteriaType,
    CohortCriteriaGroupFilter,
    CohortType,
    EntityTypes,
    RetentionEntity,
} from '~/types'

// Matches on the event key, never the display name. A flag_evaluations series carries the same name.
function entityReadsFlagCalls(node: Record<string, any> | null | undefined): boolean {
    if (isEventsNode(node)) {
        return node.event === FEATURE_FLAG_CALLED_EVENT
    }
    return isGroupNode(node) && node.nodes.some(entityReadsFlagCalls)
}

function retentionEntityReadsFlagCalls(entity: RetentionEntity | undefined): boolean {
    return entity?.type === EntityTypes.EVENTS && entity.id === FEATURE_FLAG_CALLED_EVENT
}

/**
 * Reads the insight's `query` only. An insight saved with only legacy `filters` has no query and renders blank.
 * An "All events" series is left out, because its count only drops by the flag calls and keeps working.
 * A series on an action is left out, because few saved insights reach the event through an action.
 */
export function insightReadsFlagCalls(query: Node | null | undefined): boolean {
    const source = isInsightVizNode(query) ? query.source : (query ?? undefined)
    if (isRetentionQuery(source)) {
        return (
            retentionEntityReadsFlagCalls(source.retentionFilter?.targetEntity) ||
            retentionEntityReadsFlagCalls(source.retentionFilter?.returningEntity)
        )
    }
    if (!isInsightQueryWithSeries(source)) {
        return false
    }
    const exclusions = isFunnelsQuery(source) ? (source.funnelsFilter?.exclusions ?? []) : []
    return [...source.series, ...exclusions].some(entityReadsFlagCalls)
}

export function actionReadsFlagCalls(action: Pick<ActionType, 'steps'>): boolean {
    return !!action.steps?.some((step) => step.event === FEATURE_FLAG_CALLED_EVENT)
}

/** An action keeps at least one step, so the user can't remove the flag-call steps from this one. */
export function actionOnlyReadsFlagCalls(action: Pick<ActionType, 'steps'>): boolean {
    return !!action.steps?.length && action.steps.every((step) => step.event === FEATURE_FLAG_CALLED_EVENT)
}

function criterionReadsFlagCalls(criterion: AnyCohortCriteriaType): boolean {
    return (
        criterion.type === BehavioralFilterKey.Behavioral &&
        ((criterion.event_type === TaxonomicFilterGroupType.Events && criterion.key === FEATURE_FLAG_CALLED_EVENT) ||
            (criterion.seq_event_type === TaxonomicFilterGroupType.Events &&
                criterion.seq_event === FEATURE_FLAG_CALLED_EVENT))
    )
}

function criteriaGroupReadsFlagCalls(group: CohortCriteriaGroupFilter): boolean {
    const values: (AnyCohortCriteriaType | CohortCriteriaGroupFilter)[] = group.values
    return values.some((value) =>
        isCohortCriteriaGroup(value) ? criteriaGroupReadsFlagCalls(value) : criterionReadsFlagCalls(value)
    )
}

/**
 * A static cohort keeps the people it already has, so only a dynamic cohort stops adding them.
 * An experiment's exposure cohort is left out, because its criterion belongs to the experiment.
 * A criterion on an action is left out, because few cohorts reach the event through an action.
 */
export function cohortReadsFlagCalls(cohort: Pick<CohortType, 'is_static' | 'filters' | 'experiment_set'>): boolean {
    const criteria = cohort.filters?.properties
    return !cohort.is_static && !cohort.experiment_set?.length && !!criteria && criteriaGroupReadsFlagCalls(criteria)
}
