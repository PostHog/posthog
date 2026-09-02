import { PluginEvent } from '~/plugin-scaffold'
import { EventHeaders, PipelineEvent } from '~/types'

export type ProcessPersonDecision =
    /** Person processing enabled; `invalid` is set when $process_person_profile held a non-boolean value that was ignored. */
    | { processPerson: true; invalid?: { value: unknown } }
    /** Person processing disabled, by the capture-set force-disable header or an explicit `$process_person_profile: false` property. */
    | { processPerson: false; reason: 'header' | 'property' }

/**
 * The single source of truth for whether an event gets person processing:
 * the force-disable header wins outright, otherwise only a strict boolean
 * `false` in $process_person_profile disables it; any other non-boolean
 * value is invalid and falls back to the default (enabled).
 */
export function decideProcessPerson(event: PipelineEvent | PluginEvent, headers: EventHeaders): ProcessPersonDecision {
    if (headers.force_disable_person_processing === true) {
        return { processPerson: false, reason: 'header' }
    }
    if (event.properties && '$process_person_profile' in event.properties) {
        const propValue = event.properties.$process_person_profile
        if (propValue === false) {
            return { processPerson: false, reason: 'property' }
        }
        if (propValue !== true) {
            return { processPerson: true, invalid: { value: propValue } }
        }
    }
    return { processPerson: true }
}

// used to prevent identify from being used with generic IDs
// that we can safely assume stem from a bug or mistake
const BARE_CASE_INSENSITIVE_ILLEGAL_IDS = [
    'anonymous',
    'guest',
    'distinctid',
    'distinct_id',
    'id',
    'not_authenticated',
    'email',
    'undefined',
    'true',
    'false',
]

const BARE_CASE_SENSITIVE_ILLEGAL_IDS = ['[object Object]', 'NaN', 'None', 'none', 'null', '0', 'undefined']

// we have seen illegal ids received but wrapped in double quotes
// to protect ourselves from this we'll add the single- and double-quoted versions of the illegal ids
const singleQuoteIds = (ids: string[]) => ids.map((id) => `'${id}'`)
const doubleQuoteIds = (ids: string[]) => ids.map((id) => `"${id}"`)

// some ids are illegal regardless of casing
// while others are illegal only when cased
// so, for example, we want to forbid `NaN` but not `nan`
// but, we will forbid `uNdEfInEd` and `undefined`
const CASE_INSENSITIVE_ILLEGAL_IDS = new Set(
    BARE_CASE_INSENSITIVE_ILLEGAL_IDS.concat(singleQuoteIds(BARE_CASE_INSENSITIVE_ILLEGAL_IDS)).concat(
        doubleQuoteIds(BARE_CASE_INSENSITIVE_ILLEGAL_IDS)
    )
)

const CASE_SENSITIVE_ILLEGAL_IDS = new Set(
    BARE_CASE_SENSITIVE_ILLEGAL_IDS.concat(singleQuoteIds(BARE_CASE_SENSITIVE_ILLEGAL_IDS)).concat(
        doubleQuoteIds(BARE_CASE_SENSITIVE_ILLEGAL_IDS)
    )
)

export const isDistinctIdIllegal = (id: string): boolean => {
    const trimmed = id.trim()
    return trimmed === '' || CASE_INSENSITIVE_ILLEGAL_IDS.has(id.toLowerCase()) || CASE_SENSITIVE_ILLEGAL_IDS.has(id)
}
