import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import type { ExperimentSessionEventDeltaResponseApi } from 'products/experiments/frontend/generated/api.schemas'

// Below this many days since launch an empty shelf leads with the run's age. A week is how long it
// takes before "nothing yet" stops being what every experiment looks like.
const YOUNG_EXPERIMENT_DAYS = 7

// How an empty state ends when the experiment is paused or has its exposure frozen. Neither has
// ended, so the past tense would be wrong, but neither exposes anybody either, and every other
// ending here promises a fuller answer once more people are.
const NOT_ENROLLING_TAIL =
    "Nobody new is being exposed right now, so this won't change until the experiment is running again."

/** The parts of a comparison its empty copy reads, so a caller can see what the copy depends on. */
export type ExperimentWatchEmptyDeltas = Pick<
    ExperimentSessionEventDeltaResponseApi,
    'variants' | 'min_variant_persons' | 'sessions_truncated'
>

/**
 * What the shelf's empty copy needs to know about the run itself. `ended` and `enrolling` are not
 * each other's opposite: a paused or exposure-frozen experiment has not ended, and exposes nobody
 * either, so it takes neither the past tense nor a promise of more people.
 */
export interface ExperimentWatchRunState {
    ended: boolean
    enrolling: boolean
    /** Whole days from the launch to this visit, null when it has not launched. */
    daysSinceStart: number | null
}

/** The enrollment window the comparison covered, already formatted for reading. */
export interface ExperimentWatchCoveredWindow {
    from: string
    to: string
}

/** How long this experiment has been running, for a shelf that leads with it. Null once it is no longer young. */
function youngExperimentLead({ enrolling, daysSinceStart }: ExperimentWatchRunState): string | null {
    // Only while it enrols: on a paused run its age is no longer why the shelf is thin.
    if (!enrolling || daysSinceStart === null || daysSinceStart >= YOUNG_EXPERIMENT_DAYS) {
        return null
    }
    return daysSinceStart === 0
        ? 'This experiment started today'
        : `This experiment started ${pluralize(daysSinceStart, 'day')} ago`
}

/** How many people the comparison put on both sides of the question, which is what its copy has to size itself against. */
function comparedPersons(deltas: ExperimentWatchEmptyDeltas): number {
    return deltas.variants
        .filter((variant) => variant.persons >= deltas.min_variant_persons)
        .reduce((total, variant) => total + variant.persons, 0)
}

/**
 * Nothing was compared yet, with the variant counts that say how far off it is.
 *
 * A young run leads with its age. Most readers who reach this state opened the shelf within a few
 * days of launching, and nothing else on the tab tells them an empty shelf is what every experiment
 * looks like that early rather than something being wrong.
 */
export function tooEarlyShelfCopy(
    deltas: ExperimentWatchEmptyDeltas,
    run: ExperimentWatchRunState,
    covered: ExperimentWatchCoveredWindow
): string {
    const floor = pluralize(deltas.min_variant_persons, 'exposed person', 'exposed people')
    const counts = deltas.variants
        .map((variant) => `${humanFriendlyNumber(variant.persons)} in ${variant.key}`)
        .join(', ')
    const lead = deltas.sessions_truncated ? null : youngExperimentLead(run)
    const opening = lead
        ? `${lead}, and not enough people have been exposed yet to compare behavior: this needs at least ${floor} in two variants, and has ${counts}.`
        : `Too early to compare behavior: this needs at least ${floor} in two variants, and has ${counts}.`
    // Once a cap bound the comparison, waiting adds nobody to it, so "check back" is the one promise
    // to avoid.
    const tail = run.ended
        ? 'The experiment ended before enough people were exposed to compare them.'
        : !run.enrolling
          ? NOT_ENROLLING_TAIL
          : deltas.sessions_truncated
            ? `Only people exposed between ${covered.from} and ${covered.to} were compared, so more time helps only if more people are exposed within a stretch that long.`
            : 'Check back once more people are exposed.'
    return `${opening} ${tail}`
}

/**
 * The comparison ran and found nothing, and could not have found an ordinary difference either.
 *
 * Never "nothing separated the variants": the backend reports this reason exactly when the
 * comparison could not have carded a doubling on most of what people did, so the copy says how big
 * the comparison was rather than what people did.
 */
export function underpoweredShelfCopy(
    deltas: ExperimentWatchEmptyDeltas,
    run: ExperimentWatchRunState,
    covered: ExperimentWatchCoveredWindow
): string {
    const people = humanFriendlyNumber(comparedPersons(deltas))
    const lead = deltas.sessions_truncated ? null : youngExperimentLead(run)
    if (run.ended) {
        return `Too few people to tell. ${people} people were compared, and at that size even one variant doing something twice as often would not have shown up for most events. This is not evidence that the variants behaved the same.`
    }
    const size = `at that size even one variant doing something twice as often would not show up for most events`
    if (!run.enrolling) {
        return `Too few people to tell. ${people} people were compared, and ${size}. ${NOT_ENROLLING_TAIL}`
    }
    if (deltas.sessions_truncated) {
        return `Too few people to tell. ${people} people were compared, and ${size}. Only people exposed between ${covered.from} and ${covered.to} were compared, so more time helps only if more people are exposed within a stretch that long.`
    }
    if (lead) {
        return `${lead}, and ${people} people have been compared so far. At that size even one variant doing something twice as often would not show up for most events. Check back as more people are exposed.`
    }
    return `Too few people to tell yet. ${people} people were compared, and ${size}. Check back as more people are exposed.`
}

/**
 * The comparison ran and found nothing.
 *
 * "People did the same things" is more than the ranking supports: it found nothing past its own
 * evidence bar, and a difference half the size of the one the size check asks about can still be
 * missed at a few thousand people. This reason is also where a scan whose events cannot carry that
 * size check lands, so the copy says what the shelf found and stops there.
 */
export function noSeparationShelfCopy(run: ExperimentWatchRunState): string {
    const opening = 'No clear difference showed up between the variants in the sessions compared here.'
    return run.enrolling
        ? `${opening} Differences small enough to be chance never get a card, so check back as more people are exposed.`
        : `${opening} Differences small enough to be chance never get a card.`
}

/**
 * Said on a shelf that has cards but no finding among them, because the shelves below can be full
 * of metric shortcuts and events a variant renders itself, and a reader left to infer "no
 * differences" from their absence reads the surface as broken instead.
 */
export function noStandoutBehaviorCaption(run: ExperimentWatchRunState): string {
    const found = run.ended
        ? 'No variant showed clearly different behavior in its recorded sessions.'
        : 'No variant shows clearly different behavior in its recorded sessions' + (run.enrolling ? ' yet.' : '.')
    return run.enrolling
        ? `${found} Differences small enough to be chance don't get a card, so this can change as more people are exposed.`
        : `${found} Differences small enough to be chance don't get a card.`
}
