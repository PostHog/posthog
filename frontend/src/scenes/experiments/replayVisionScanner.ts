import { convertUniversalFiltersToRecordingsQuery } from 'scenes/session-recordings/filters/recordingsQueryConversions'

import {
    FilterLogicalOperator,
    type Experiment,
    type RecordingUniversalFilters,
    type UniversalFiltersGroupValue,
} from '~/types'

import type { ReplayScannerApi } from 'products/replay_vision/frontend/generated/api.schemas'
import {
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    scannerToApiBody,
} from 'products/replay_vision/frontend/replay_scanners/types'

import { applySessionLinkability, getExposureFallbackFilter, getViewRecordingFiltersForVariant } from './utils'

const SCANNER_NAME_MAX_LENGTH = 255

/**
 * A classifier, not a summarizer: a fixed tag set is what makes two variants comparable, and free
 * text does not aggregate into a per-variant delta. `never-reached` is the escape tag — most
 * exposed sessions never touch the changed surface, and without somewhere to put them the model is
 * forced to invent friction on irrelevant sessions, which shows up as a fake delta between variants.
 */
export const EXPERIMENT_SCANNER_TAGS = [
    'never-reached',
    'smooth',
    'hesitation',
    'confusion',
    'error-or-dead-end',
] as const

/**
 * The variant keys are deliberately absent: the scanner cannot know which variant a session belongs
 * to, and a prompt that names them gets confident, wrong variant labels attached to observations.
 * Attribution comes from joining observations back to the exposure event at readout instead.
 */
export function experimentScannerPrompt(experiment: Experiment): string {
    const hypothesis = experiment.description?.trim()
    return [
        'Classify what this participant did after the point where the experiment change would first be visible to them. Ignore anything earlier in the session.',
        // The hypothesis is optional at creation, so the required name is the fallback grounding:
        // without any hint at the changed surface, the tags have nothing to distinguish sessions on.
        hypothesis
            ? `What the experiment changes: ${hypothesis}`
            : `The experiment has no written hypothesis. Its name is "${experiment.name.trim()}", so infer the changed surface from that name.`,
        'Pick one tag:',
        '- never-reached: they never got to the part of the product the experiment changes.',
        '- smooth: they reached it and moved on without visible trouble.',
        '- hesitation: they reached it and paused, re-read, or went back and forth before acting.',
        '- confusion: they reached it and acted as if they misread it, for example wrong clicks, repeated attempts, or wandering.',
        '- error-or-dead-end: they hit an error, an empty state, or a point with no way forward.',
        'Do not guess which variant of the experiment this session was in, and do not mention variants. Describe only what the participant did.',
    ].join('\n\n')
}

/**
 * The scanner's population: the experiment's exposed sessions, with the same session-linkability
 * handling the recordings surfaces use. A server-side exposure event carries no `$session_id`, so
 * without this the query matches zero sessions forever while the scanner looks healthy.
 *
 * Advisory only here, unlike on the recordings surfaces: the check reports "never seen with a
 * session id", which at creation time is mostly "never seen at all" — the flag is minutes old. So
 * an unlinkable exposure downgrades to the fallback filter where one exists, and otherwise keeps
 * the exposure filter. It must never fall through to the empty filter list `applySessionLinkability`
 * returns for that case, which would scan every recording in the project.
 */
export function experimentScannerFilters(
    experiment: Experiment,
    unlinkableEventNames: Set<string>
): { filters: UniversalFiltersGroupValue[]; usedExposureFallback: boolean } {
    const exposureFilters = getViewRecordingFiltersForVariant(experiment)
    const { filters, usedExposureFallback, exposureUnlinkable } = applySessionLinkability(
        exposureFilters,
        unlinkableEventNames,
        getExposureFallbackFilter(experiment)
    )
    return { filters: exposureUnlinkable ? exposureFilters : filters, usedExposureFallback }
}

export function experimentScannerBody(
    experiment: Experiment,
    filters: UniversalFiltersGroupValue[],
    usedExposureFallback: boolean
): ReplayScannerApi {
    const nameSuffix = ` (#${experiment.id})`
    const name = `${experiment.name.slice(0, SCANNER_NAME_MAX_LENGTH - nameSuffix.length)}${nameSuffix}`
    const universalFilters: RecordingUniversalFilters = {
        filter_test_accounts: experiment.exposure_criteria?.filterTestAccounts ?? false,
        duration: [],
        filter_group: {
            type: FilterLogicalOperator.And,
            values: [{ type: FilterLogicalOperator.And, values: filters }],
        },
    }

    return scannerToApiBody({
        name,
        description: usedExposureFallback
            ? "Classifies what participants do in sessions where this experiment's feature flag was active."
            : 'Classifies what participants do after they are exposed to this experiment.',
        scanner_type: 'classifier',
        scanner_config: {
            prompt: experimentScannerPrompt(experiment),
            tags: [...EXPERIMENT_SCANNER_TAGS],
            multi_label: false,
        },
        // `model` is required by the create serializer; the rest of the product picks the same defaults.
        provider: DEFAULT_PROVIDER,
        model: DEFAULT_MODEL,
        query: convertUniversalFiltersToRecordingsQuery(universalFilters),
        // Enabling starts real credit spend, so that stays a human decision on the scanner itself.
        enabled: false,
    })
}
