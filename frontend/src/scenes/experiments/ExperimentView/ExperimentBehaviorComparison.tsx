import { useActions, useValues } from 'kea'

import { IconChevronDown, IconInfo } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import { Experiment } from '~/types'

import {
    ExperimentWatchCardStrengthEnumApi,
    ExperimentWatchCardKindEnumApi,
    type ExperimentSessionEventDeltaResponseApi,
    type ExperimentWatchCardApi,
} from 'products/experiments/frontend/generated/api.schemas'

import { experimentReplayTabLogic } from './experimentReplayTabLogic'
import { VariantTag } from './VariantTag'

const STRENGTH_WORD: Record<Exclude<ExperimentWatchCardStrengthEnumApi, 'only'>, string> = {
    far_more: 'Far more common',
    more: 'More common',
    slightly_more: 'Slightly more common',
}

/**
 * The one comparative sentence a card gets, in bands rather than numbers. The band comes from the
 * conservative end of the difference; wording it as a multiple would put an effect size on screen,
 * which is the results tab's job. Do not reintroduce one.
 *
 * `armKeys` is what the comparison actually pooled, not every variant the flag defines — a variant
 * below the evidence floor was never in the "other variants" this card is measured against.
 */
function cardSentence(card: ExperimentWatchCardApi, armKeys: string[]): string {
    if (card.kind === ExperimentWatchCardKindEnumApi.Metric) {
        return card.metric_name ? `Watch the ${card.metric_name} metric happen` : 'Watch this metric event happen'
    }
    const others =
        armKeys.length > 2 ? 'the other variants' : (armKeys.find((key) => key !== card.variant) ?? 'the other variant')
    if (card.strength === ExperimentWatchCardStrengthEnumApi.Only) {
        return `Seen here, never in ${others}`
    }
    return `${STRENGTH_WORD[card.strength ?? ExperimentWatchCardStrengthEnumApi.More]} than in ${others}`
}

function WatchCard({
    card,
    selected,
    armKeys,
    onSelect,
}: {
    card: ExperimentWatchCardApi
    selected: boolean
    armKeys: string[]
    onSelect: (card: ExperimentWatchCardApi | null) => void
}): JSX.Element {
    return (
        // The whole card is one control, so the control is a real button rather than a click
        // handler on the card: picking a card is the only thing to do on this shelf, and a
        // clickable div can't be reached or fired from the keyboard.
        <LemonCard hoverEffect focused={selected} className="w-60 shrink-0 p-0" data-attr="experiment-watch-card">
            <button
                type="button"
                aria-pressed={selected}
                onClick={() => onSelect(selected ? null : card)}
                className="flex w-full cursor-pointer flex-col gap-1 p-3 text-left"
            >
                <VariantTag variantKey={card.variant} />
                <div className="break-all text-sm font-semibold leading-tight">{card.event}</div>
                <div className="text-xs text-secondary">{cardSentence(card, armKeys)}</div>
                <div className="mt-1 flex w-full items-center justify-between text-xs">
                    <span className="text-secondary">{pluralize(card.recording_count, 'recording')}</span>
                    <span className="font-medium">{selected ? 'Showing below' : 'Watch'}</span>
                </div>
            </button>
        </LemonCard>
    )
}

function Shelf({
    title,
    note,
    cards,
    selectedCard,
    armKeys,
    onSelect,
}: {
    title: string
    note?: string
    cards: ExperimentWatchCardApi[]
    selectedCard: ExperimentWatchCardApi | null
    armKeys: string[]
    onSelect: (card: ExperimentWatchCardApi | null) => void
}): JSX.Element | null {
    if (cards.length === 0) {
        return null
    }
    return (
        <div className="flex flex-col gap-1.5">
            <div className="flex items-baseline gap-2">
                <span className="text-xs font-semibold uppercase tracking-wide text-secondary">{title}</span>
                {note && <span className="text-xs text-muted">{note}</span>}
            </div>
            <div className="flex flex-wrap gap-2">
                {cards.map((card) => (
                    <WatchCard
                        key={`${card.kind}-${card.event}-${card.variant}`}
                        card={card}
                        selected={
                            selectedCard !== null &&
                            selectedCard.event === card.event &&
                            selectedCard.variant === card.variant &&
                            selectedCard.kind === card.kind
                        }
                        armKeys={armKeys}
                        onSelect={onSelect}
                    />
                ))}
            </div>
        </div>
    )
}

/** The toggle alone, so it can sit in the tab's filter row while the shelves render below it. */
export function ExperimentBehaviorComparisonToggle({ experiment }: { experiment: Experiment }): JSX.Element | null {
    const logic = experimentReplayTabLogic({ experiment })
    const { behaviorComparisonAvailable, behaviorComparisonOpen } = useValues(logic)
    const { toggleBehaviorComparison } = useActions(logic)

    if (!behaviorComparisonAvailable) {
        return null
    }

    return (
        <LemonButton
            size="small"
            type="secondary"
            // One glyph rotated rather than a chevron pair: IconChevronRight is drawn three times
            // taller than IconChevronDown in this set, so the two states would change size.
            icon={<IconChevronDown className={cn('transition-transform', !behaviorComparisonOpen && '-rotate-90')} />}
            onClick={() => toggleBehaviorComparison()}
            aria-expanded={behaviorComparisonOpen}
            tooltip="Groups of recordings worth watching: behavior one variant shows more of, friction, and your metric events happening on screen."
            data-attr="experiment-behavior-comparison-toggle"
        >
            What to watch
        </LemonButton>
    )
}

export function ExperimentBehaviorComparison({ experiment }: { experiment: Experiment }): JSX.Element | null {
    const logic = experimentReplayTabLogic({ experiment })
    const {
        behaviorComparisonAvailable,
        behaviorComparisonOpen,
        sessionEventDeltas,
        sessionEventDeltasLoading,
        sessionEventDeltasError,
        selectedWatchCard,
    } = useValues(logic)
    const { selectWatchCard, loadSessionEventDeltas } = useActions(logic)

    // Nothing at all when closed, rather than an empty spacer: the toggle lives in the filter row
    // now, so a wrapper left behind here would push the recordings list down for no reason.
    if (!behaviorComparisonAvailable || !behaviorComparisonOpen) {
        return null
    }

    return (
        <div className="mb-4">
            {sessionEventDeltasError !== null ? (
                <div className="flex items-center gap-2 text-xs text-secondary">
                    <span>Couldn't pick recordings to watch: {sessionEventDeltasError}</span>
                    <LemonButton size="xsmall" type="secondary" onClick={() => loadSessionEventDeltas()}>
                        Try again
                    </LemonButton>
                </div>
            ) : sessionEventDeltasLoading || !sessionEventDeltas ? (
                <div className="flex items-center gap-2 text-xs text-secondary">
                    <Spinner textColored />
                    <span>Comparing what happened in each variant's sessions…</span>
                </div>
            ) : (
                <WatchShelves deltas={sessionEventDeltas} selectedCard={selectedWatchCard} onSelect={selectWatchCard} />
            )}
        </div>
    )
}

function WatchShelves({
    deltas,
    selectedCard,
    onSelect,
}: {
    deltas: ExperimentSessionEventDeltaResponseApi
    selectedCard: ExperimentWatchCardApi | null
    onSelect: (card: ExperimentWatchCardApi | null) => void
}): JSX.Element {
    if (deltas.too_early) {
        return (
            <LemonBanner type="info">
                Too early to compare behavior: this needs at least{' '}
                {pluralize(deltas.min_arm_persons, 'exposed person', 'exposed people')} in two variants, and has{' '}
                {deltas.arms.map((arm) => `${humanFriendlyNumber(arm.persons)} in ${arm.key}`).join(', ')}.
            </LemonBanner>
        )
    }

    // What the comparison pooled, which is not every variant the flag defines: one below the
    // evidence floor is left out of the comparison, so a card's sentence must not name it as
    // something the card was measured against.
    const armKeys = deltas.arms.filter((arm) => arm.persons >= deltas.min_arm_persons).map((arm) => arm.key)
    const behaviorCards = deltas.cards.filter((card) => card.kind === ExperimentWatchCardKindEnumApi.Behavior)
    const frictionCards = deltas.cards.filter((card) => card.kind === ExperimentWatchCardKindEnumApi.Friction)
    const metricCards = deltas.cards.filter((card) => card.kind === ExperimentWatchCardKindEnumApi.Metric)

    return (
        <div className="flex flex-col gap-3">
            <ShelfCaption deltas={deltas} />
            {deltas.cards.length === 0 ? (
                <div className="text-xs text-secondary">
                    No variant shows clearly different behavior in its recorded sessions yet. Differences small enough
                    to be chance don't get a card, so this can change as more people are exposed.
                </div>
            ) : (
                <>
                    <Shelf
                        title="Behaves differently"
                        cards={behaviorCards}
                        selectedCard={selectedCard}
                        armKeys={armKeys}
                        onSelect={onSelect}
                    />
                    <Shelf
                        title="Friction"
                        cards={frictionCards}
                        selectedCard={selectedCard}
                        armKeys={armKeys}
                        onSelect={onSelect}
                    />
                    <Shelf
                        title="Metrics"
                        note="See your metric events happen. The Results tab measures them."
                        cards={metricCards}
                        selectedCard={selectedCard}
                        armKeys={armKeys}
                        onSelect={onSelect}
                    />
                </>
            )}
        </div>
    )
}

/**
 * Read before the cards, not after them: what a reader has to know to interpret a shelf is that it
 * points at recordings rather than measuring anything, and the window it actually covered. The
 * full method sits behind the info icon.
 */
function ShelfCaption({ deltas }: { deltas: ExperimentSessionEventDeltaResponseApi }): JSX.Element {
    // A window that ran out inside a single day reads wrong as two identical dates, and "Aug 3 to
    // Aug 3" hides that only a few hours were covered.
    const sameDay = dayjs(deltas.date_from).isSame(dayjs(deltas.date_to), 'day')
    const format = sameDay ? 'MMM D, HH:mm' : 'MMM D'
    const details = [
        'Each variant is compared against the others on which events people did, counting each person once, in the first session they were exposed in. Cards only appear where the difference is too big to be chance, and only with recordings that actually exist.',
        'Page views, autocaptures and the exposure event are never compared, since their names describe a mechanism rather than something a person did.',
        deltas.metric_events.length > 0
            ? `The events this experiment measures (${deltas.metric_events.join(', ')}) are never compared here either: the Results tab states what happened to them. Their cards only link to recordings.`
            : null,
        deltas.filter_test_accounts ? 'Test accounts are excluded.' : null,
        deltas.multiple_variant_persons > 0
            ? `${pluralize(deltas.multiple_variant_persons, 'person', 'people')} saw more than one variant and ${
                  deltas.multiple_variant_persons === 1 ? 'is' : 'are'
              } left out.`
            : null,
        deltas.used_exposure_fallback
            ? 'Sessions are matched on the feature flag being active, since no exposure event can be matched to a recording here.'
            : null,
        deltas.sessions_truncated
            ? 'The experiment has more exposed sessions than one comparison covers, so the window is the most recent stretch that fits, not the whole run.'
            : null,
        deltas.events_truncated ? 'The project has more event types than one comparison can rank.' : null,
    ].filter(Boolean)

    return (
        <div className="flex items-center gap-1 text-xs text-secondary">
            <span>
                These highlight which recordings might be worth watching. They don't say which variant is doing better,
                the way metrics do. From recorded sessions between {dayjs(deltas.date_from).format(format)} and{' '}
                {dayjs(deltas.date_to).format(format)}.
            </span>
            <Tooltip
                title={
                    <div className="flex flex-col gap-1">
                        {details.map((detail, index) => (
                            <span key={index}>{detail}</span>
                        ))}
                    </div>
                }
            >
                <IconInfo className="shrink-0 text-sm" />
            </Tooltip>
        </div>
    )
}
