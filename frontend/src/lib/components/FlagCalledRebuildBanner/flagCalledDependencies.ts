import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { BehavioralFilterKey } from 'scenes/cohorts/CohortFilters/types'
import { isCohortCriteriaGroup } from 'scenes/cohorts/cohortUtils'
import { getActivationConfig } from 'scenes/experiments/exposureContract'
import { FEATURE_FLAG_CALLED_EVENT } from 'scenes/feature-flags/featureFlagUsageQueries'

import { Node } from '~/queries/schema/schema-general'
import {
    isActionsNode,
    isEventsNode,
    isFunnelsQuery,
    isGroupNode,
    isInsightQueryWithSeries,
    isInsightVizNode,
    isRetentionQuery,
} from '~/queries/utils'
import {
    AnyCohortCriteriaType,
    CohortCriteriaGroupFilter,
    CohortType,
    EntityTypes,
    Experiment,
    RetentionEntity,
} from '~/types'

/** The parts of a saved artifact that can read `$feature_flag_called` from the events table. */
export interface FlagCalledReferences {
    /** The artifact names the event itself. */
    readsEvent: boolean
    /** Actions the artifact uses. An action reads the event when one of its steps matches it. */
    actionIds: number[]
}

const NO_REFERENCES: FlagCalledReferences = { readsEvent: false, actionIds: [] }

export function combineReferences(references: FlagCalledReferences[]): FlagCalledReferences {
    return {
        readsEvent: references.some(({ readsEvent }) => readsEvent),
        actionIds: references.flatMap(({ actionIds }) => actionIds),
    }
}

function eventReference(event: unknown): FlagCalledReferences {
    return { readsEvent: event === FEATURE_FLAG_CALLED_EVENT, actionIds: [] }
}

function actionReference(actionId: unknown): FlagCalledReferences {
    const id = Number(actionId)
    return Number.isInteger(id) ? { readsEvent: false, actionIds: [id] } : NO_REFERENCES
}

// Matches on the event key, never the display name. A flag_evaluations series carries the same name.
function entityReferences(node: Record<string, any> | null | undefined): FlagCalledReferences {
    if (isEventsNode(node)) {
        return eventReference(node.event)
    }
    if (isActionsNode(node)) {
        return actionReference(node.id)
    }
    if (isGroupNode(node)) {
        return combineReferences(node.nodes.map(entityReferences))
    }
    return NO_REFERENCES
}

function retentionEntityReferences(entity: RetentionEntity | undefined): FlagCalledReferences {
    if (entity?.type === EntityTypes.EVENTS) {
        return eventReference(entity.id)
    }
    if (entity?.type === EntityTypes.ACTIONS) {
        return actionReference(entity.id)
    }
    return NO_REFERENCES
}

/**
 * Reads the insight's `query` only. An insight saved with only legacy `filters` has no query and renders blank.
 * An "All events" series is left out, because its count only drops by the flag calls and keeps working.
 */
export function insightFlagCalledReferences(query: Node | null | undefined): FlagCalledReferences {
    const source = isInsightVizNode(query) ? query.source : (query ?? undefined)
    if (isRetentionQuery(source)) {
        return combineReferences([
            retentionEntityReferences(source.retentionFilter?.targetEntity),
            retentionEntityReferences(source.retentionFilter?.returningEntity),
        ])
    }
    if (!isInsightQueryWithSeries(source)) {
        return NO_REFERENCES
    }
    const exclusions = isFunnelsQuery(source) ? (source.funnelsFilter?.exclusions ?? []) : []
    return combineReferences([...source.series, ...exclusions].map(entityReferences))
}

/** The step shape that both the generated `ActionApi` and `ActionType` satisfy. */
export interface FlagCalledAction {
    id: number
    steps?: { event?: string | null }[] | null
}

export function actionReadsFlagCalls(action: Pick<FlagCalledAction, 'steps'>): boolean {
    return !!action.steps?.some((step) => step.event === FEATURE_FLAG_CALLED_EVENT)
}

/** An action keeps at least one step, so the user can't remove the flag-call steps from this one. */
export function actionOnlyReadsFlagCalls(action: Pick<FlagCalledAction, 'steps'>): boolean {
    return !!action.steps?.length && action.steps.every((step) => step.event === FEATURE_FLAG_CALLED_EVENT)
}

export function actionFlagCalledReferences(action: Pick<FlagCalledAction, 'steps'>): FlagCalledReferences {
    return { readsEvent: actionReadsFlagCalls(action), actionIds: [] }
}

function taxonomicReferences(
    groupType: TaxonomicFilterGroupType | null | undefined,
    value: unknown
): FlagCalledReferences {
    if (groupType === TaxonomicFilterGroupType.Events) {
        return eventReference(value)
    }
    if (groupType === TaxonomicFilterGroupType.Actions) {
        return actionReference(value)
    }
    return NO_REFERENCES
}

function criterionReferences(criterion: AnyCohortCriteriaType): FlagCalledReferences {
    if (criterion.type !== BehavioralFilterKey.Behavioral) {
        return NO_REFERENCES
    }
    return combineReferences([
        taxonomicReferences(criterion.event_type, criterion.key),
        taxonomicReferences(criterion.seq_event_type, criterion.seq_event),
    ])
}

function criteriaGroupReferences(group: CohortCriteriaGroupFilter): FlagCalledReferences {
    const values: (AnyCohortCriteriaType | CohortCriteriaGroupFilter)[] = group.values
    return combineReferences(
        values.map((value) =>
            isCohortCriteriaGroup(value) ? criteriaGroupReferences(value) : criterionReferences(value)
        )
    )
}

/**
 * A static cohort keeps the people it already has, so only a dynamic cohort stops adding them.
 * An experiment's exposure cohort is left out, because the experiment's own banner covers it.
 */
export function cohortFlagCalledReferences(
    cohort: Pick<CohortType, 'is_static' | 'filters' | 'experiment_set'>
): FlagCalledReferences {
    const criteria = cohort.filters?.properties
    return cohort.is_static || cohort.experiment_set?.length || !criteria
        ? NO_REFERENCES
        : criteriaGroupReferences(criteria)
}

/**
 * The default exposure is left out, because the exposure query counts $experiment_exposure for calls from
 * September 1 on. An action exposure and an activation config still match rows in the events table.
 * An experiment that ended keeps its exposures, because the events table keeps the flag calls it already has.
 * Legacy experiments are left out, because their results stop being available on October 15, 2026.
 */
export function experimentFlagCalledReferences(experiment: Experiment): FlagCalledReferences {
    if (!experiment.start_date || experiment.end_date || experiment.archived) {
        return NO_REFERENCES
    }
    const exposureConfig = experiment.exposure_criteria?.exposure_config
    if (isActionsNode(exposureConfig)) {
        return actionReference(exposureConfig.id)
    }
    const activationConfig = getActivationConfig(experiment.exposure_criteria)
    if (!activationConfig) {
        return NO_REFERENCES
    }
    return isActionsNode(activationConfig)
        ? actionReference(activationConfig.id)
        : eventReference(activationConfig.event)
}

/** False until the referenced actions load, so a banner that depends on an action waits rather than guessing. */
export function dependsOnFlagCalls(references: FlagCalledReferences, actions: FlagCalledAction[]): boolean {
    return (
        references.readsEvent ||
        references.actionIds.some((id) => actions.some((action) => action.id === id && actionReadsFlagCalls(action)))
    )
}
