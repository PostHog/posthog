import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { getCoreFilterDefinition } from '~/taxonomy/helpers'

import { AutoresearchPipelineApi } from './generated/api.schemas'

/** The target event's display name: "Pageview" for `$pageview`, and a custom event's own name. */
export function eventLabel(targetEvent: string): string {
    return getCoreFilterDefinition(targetEvent, TaxonomicFilterGroupType.Events)?.label ?? targetEvent
}

/**
 * The target event as a name inside a sentence. Event names are nouns or past-tense phrases
 * ("File downloaded"), so quotes keep "did File downloaded" from reading as a broken verb.
 */
export function eventName(targetEvent: string): string {
    return `“${eventLabel(targetEvent)}”`
}

/** The question a model answers, in plain words, built from its target and horizon. */
export function pipelineQuestion({
    target_event,
    horizon_days,
}: Pick<AutoresearchPipelineApi, 'target_event' | 'horizon_days'>): string {
    const target = eventName(target_event)
    if (!horizon_days) {
        return `Who will do ${target}?`
    }
    return horizon_days === 1
        ? `Who will do ${target} in the next day?`
        : `Who will do ${target} in the next ${horizon_days} days?`
}

/** The heading of a model card and of the detail header: a name the user wrote as a question, else the generated question. */
export function pipelineTitle(
    pipeline: Pick<AutoresearchPipelineApi, 'name' | 'target_event' | 'horizon_days'>
): string {
    const name = pipeline.name?.trim() ?? ''
    return name.endsWith('?') ? name : pipelineQuestion(pipeline)
}

function words(text: string): string {
    return text
        .toLowerCase()
        .replace(/[^\p{L}\p{N}]+/gu, ' ')
        .trim()
}

/** The model name under the title. Null when the name is the title or only repeats part of it. */
export function pipelineSubtitle(
    pipeline: Pick<AutoresearchPipelineApi, 'name' | 'target_event' | 'horizon_days'>
): string | null {
    const name = words(pipeline.name ?? '')
    if (!name) {
        return null
    }
    return ` ${words(pipelineTitle(pipeline))} `.includes(` ${name} `) ? null : pipeline.name
}
