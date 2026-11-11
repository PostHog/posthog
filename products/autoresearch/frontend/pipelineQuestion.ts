import { AutoresearchPipelineApi } from './generated/api.schemas'

/**
 * The target event as a name inside a sentence. Event names are nouns or past-tense phrases
 * ("File downloaded"), so quotes keep "did File downloaded" from reading as a broken verb.
 */
export function eventName(targetEvent: string): string {
    return `“${targetEvent}”`
}

/** The question a model answers, in plain words. The model list cards and the detail header both show it. */
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

function words(text: string): string {
    return text
        .toLowerCase()
        .replace(/[^\p{L}\p{N}]+/gu, ' ')
        .trim()
}

/** The model name under the question in the detail header. Null when the name only repeats part of the question. */
export function pipelineSubtitle(
    pipeline: Pick<AutoresearchPipelineApi, 'name' | 'target_event' | 'horizon_days'>
): string | null {
    const name = words(pipeline.name ?? '')
    if (!name) {
        return null
    }
    return ` ${words(pipelineQuestion(pipeline))} `.includes(` ${name} `) ? null : pipeline.name
}
