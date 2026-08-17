import { useActions, useValues } from 'kea'

import { IconChevronDown, IconInfo, IconPlay } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'
import { asDisplay } from 'scenes/persons/person-utils'

import { Experiment } from '~/types'

import {
    ExperimentWatchCardStrengthEnumApi,
    ExperimentWatchCardKindEnumApi,
    type ExperimentSessionEventDeltaResponseApi,
    type ExperimentWatchCardApi,
} from 'products/experiments/frontend/generated/api.schemas'

import { hasEnded } from '../experimentStatus'
import { type ExperimentReplayRecording, experimentReplayTabLogic } from './experimentReplayTabLogic'
import { VariantTag } from './VariantTag'

const STRENGTH_WORD: Record<Exclude<ExperimentWatchCardStrengthEnumApi, 'only'>, string> = {
    far_more: 'Far more common',
    more: 'More common',
    slightly_more: 'Slightly more common',
}

function otherVariants(card: ExperimentWatchCardApi, armKeys: string[]): string {
    const named = armKeys.length === 2 ? armKeys.find((key) => key !== card.variant) : undefined
    return named ?? pluralize(armKeys.length - 1, 'the other variant', undefined, false)
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
    const others = otherVariants(card, armKeys)
    if (card.kind === ExperimentWatchCardKindEnumApi.VariantOnly) {
        return card.strength === ExperimentWatchCardStrengthEnumApi.Only
            ? `Never fired in ${others}`
            : `Almost never fired in ${others}`
    }
    if (card.strength === ExperimentWatchCardStrengthEnumApi.Only) {
        return `Seen here, never in ${others}`
    }
    return `${STRENGTH_WORD[card.strength ?? ExperimentWatchCardStrengthEnumApi.More]} than in ${others}`
}

/**
 * How many recordings a card can show, written the way it has to be read. A count that reached the
 * ceiling is a floor, and a bare number beside an event name reads as how often that event
 * happened, which the Results tab answers over a different window and unit. Saturated counts are
 * also the ones that look equal across variants when the underlying event isn't.
 */
function recordingCount(card: ExperimentWatchCardApi, maxRecordings: number): string {
    return card.recording_count >= maxRecordings ? `${maxRecordings}+` : `${card.recording_count}`
}

/**
 * A comparison card whose event one of the experiment's metrics counts. The tag is what stops the
 * card being read as a second answer about that metric: the results measure the same event over the
 * whole run window, and this card only points at recordings.
 */
function MetricSourceTag({ metricName }: { metricName: string }): JSX.Element {
    return (
        <Tooltip
            title={`The Results tab measures this event as your "${metricName}" metric. This card only points at recordings of it happening, it doesn't say how the metric moved.`}
        >
            <LemonTag size="small" type="muted" className="max-w-full">
                <span className="truncate">Metric: {metricName}</span>
            </LemonTag>
        </Tooltip>
    )
}

function WatchCard({
    card,
    selected,
    armKeys,
    maxRecordings,
    onSelect,
}: {
    card: ExperimentWatchCardApi
    selected: boolean
    armKeys: string[]
    maxRecordings: number
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
                className="flex h-full w-full cursor-pointer flex-col gap-1 p-3 text-left"
            >
                <VariantTag variantKey={card.variant} />
                <div className="break-all text-sm font-semibold leading-tight">{card.event}</div>
                <div className="text-xs text-secondary">{cardSentence(card, armKeys)}</div>
                {card.metric_name && <MetricSourceTag metricName={card.metric_name} />}
                {/* Pushed to the bottom rather than following the text, so the footers line up
                    across a row whose cards carry different numbers of lines. */}
                <div className="mt-auto flex w-full items-center justify-between pt-2 text-xs">
                    <span className="text-secondary">
                        {recordingCount(card, maxRecordings)}{' '}
                        {pluralize(card.recording_count, 'recording', undefined, false)}
                    </span>
                    <span className="font-medium">{selected ? 'Showing below' : 'Watch'}</span>
                </div>
            </button>
        </LemonCard>
    )
}

/**
 * One card per metric event rather than one per (event, variant): the per-variant shape puts ten
 * near-identical cards claiming nothing beside one real finding on a five-variant experiment. The
 * variant chips do the per-variant work, each picking that variant's own recordings.
 */
function MetricEventCard({
    event,
    metricName,
    cards,
    selectedCard,
    maxRecordings,
    onSelect,
}: {
    event: string
    metricName: string | null
    cards: ExperimentWatchCardApi[]
    selectedCard: ExperimentWatchCardApi | null
    maxRecordings: number
    onSelect: (card: ExperimentWatchCardApi | null) => void
}): JSX.Element {
    return (
        <LemonCard className="w-60 shrink-0 p-3" data-attr="experiment-watch-metric-card">
            <div className="flex h-full flex-col gap-1">
                <div className="break-all text-sm font-semibold leading-tight">{event}</div>
                <div className="text-xs text-secondary">
                    {metricName ? `Watch the ${metricName} metric happen` : 'Watch this metric event happen'}
                </div>
                <div className="mt-auto flex flex-wrap gap-1 pt-2">
                    {cards.map((card) => {
                        const selected = isSameCard(selectedCard, card)
                        return (
                            <LemonButton
                                key={card.variant}
                                size="xsmall"
                                type="secondary"
                                active={selected}
                                aria-pressed={selected}
                                onClick={() => onSelect(selected ? null : card)}
                                tooltip={`${recordingCount(card, maxRecordings)} ${pluralize(
                                    card.recording_count,
                                    'recording',
                                    undefined,
                                    false
                                )} in ${card.variant}`}
                                data-attr="experiment-watch-metric-variant"
                            >
                                <span className="flex items-center gap-1.5">
                                    <VariantTag variantKey={card.variant} fontSize={11} />
                                    {/* The count stays on the chip's face rather than in the
                                        tooltip: without it two variants of the same event look
                                        interchangeable. */}
                                    <span className="text-xs text-secondary">
                                        {recordingCount(card, maxRecordings)}
                                    </span>
                                </span>
                            </LemonButton>
                        )
                    })}
                </div>
            </div>
        </LemonCard>
    )
}

function isSameCard(selectedCard: ExperimentWatchCardApi | null, card: ExperimentWatchCardApi): boolean {
    return (
        selectedCard !== null &&
        selectedCard.event === card.event &&
        selectedCard.variant === card.variant &&
        selectedCard.kind === card.kind
    )
}

/** Title, optional note, cards, and the strip for whichever card on this shelf is selected. */
function ShelfFrame({
    title,
    note,
    cards,
    selectedCard,
    recordingsById,
    maxRecordings,
    onOpenHighlight,
    children,
}: {
    title: string
    note?: string
    cards: ExperimentWatchCardApi[]
    selectedCard: ExperimentWatchCardApi | null
    recordingsById: Map<string, ExperimentReplayRecording>
    maxRecordings: number
    onOpenHighlight: (card: ExperimentWatchCardApi, sessionId: string, position: number) => void
    children: React.ReactNode
}): JSX.Element {
    // The strip belongs to the shelf holding the selected card, not to the bottom of the whole
    // panel: rendered once below every shelf it sat three sections away from the card that opened
    // it, with nothing on screen tying the two together.
    const selectedHere = cards.find((card) => isSameCard(selectedCard, card)) ?? null
    return (
        <div className="flex flex-col gap-1.5">
            <div className="flex items-baseline gap-2">
                <span className="text-xs font-semibold uppercase tracking-wide text-secondary">{title}</span>
                {note && <span className="text-xs text-muted">{note}</span>}
            </div>
            {children}
            {selectedHere && (
                <HighlightList
                    card={selectedHere}
                    recordingsById={recordingsById}
                    maxRecordings={maxRecordings}
                    onOpenHighlight={onOpenHighlight}
                />
            )}
        </div>
    )
}

function Shelf({
    title,
    note,
    cards,
    selectedCard,
    armKeys,
    maxRecordings,
    onSelect,
    recordingsById,
    onOpenHighlight,
}: {
    title: string
    note?: string
    cards: ExperimentWatchCardApi[]
    selectedCard: ExperimentWatchCardApi | null
    armKeys: string[]
    maxRecordings: number
    onSelect: (card: ExperimentWatchCardApi | null) => void
    recordingsById: Map<string, ExperimentReplayRecording>
    onOpenHighlight: (card: ExperimentWatchCardApi, sessionId: string, position: number) => void
}): JSX.Element | null {
    if (cards.length === 0) {
        return null
    }
    return (
        <ShelfFrame
            title={title}
            note={note}
            cards={cards}
            selectedCard={selectedCard}
            recordingsById={recordingsById}
            maxRecordings={maxRecordings}
            onOpenHighlight={onOpenHighlight}
        >
            <div className="flex flex-wrap gap-2">
                {cards.map((card) => (
                    <WatchCard
                        key={`${card.kind}-${card.event}-${card.variant}`}
                        card={card}
                        selected={isSameCard(selectedCard, card)}
                        armKeys={armKeys}
                        maxRecordings={maxRecordings}
                        onSelect={onSelect}
                    />
                ))}
            </div>
        </ShelfFrame>
    )
}

/**
 * Which of the selected card's recordings to open first. The recordings list below sorts by its own
 * order, so a card that only narrowed the list still left every row looking the same; these are the
 * ones that differ, and each says how.
 *
 * Rendered as recordings rather than as a row of labels: a chip reading "6 rage clicks" beside a
 * card reads as a statistic about the card, which is the opposite of what it is. Duration and
 * person come from the page the playlist has already loaded, since a card's session ids are exactly
 * what the list is filtered to.
 */
function HighlightList({
    card,
    recordingsById,
    maxRecordings,
    onOpenHighlight,
}: {
    card: ExperimentWatchCardApi
    recordingsById: Map<string, ExperimentReplayRecording>
    maxRecordings: number
    onOpenHighlight: (card: ExperimentWatchCardApi, sessionId: string, position: number) => void
}): JSX.Element {
    if (card.highlights.length === 0) {
        // Silence here would read as the strip being broken; an empty strip is itself the answer
        // to "which one should I open?". Worded without a claim about the recordings themselves,
        // because highlights can also be missing when the viewer can't open the recordings that
        // carried them.
        return (
            <div className="text-xs text-muted" data-attr="experiment-watch-no-highlights">
                No standout recordings to suggest here. Start with any of them in the list below.
            </div>
        )
    }
    return (
        <div className="flex flex-col gap-1" data-attr="experiment-watch-highlights">
            <div className="flex items-baseline gap-2">
                <span className="text-xs text-muted">
                    {pluralize(card.highlights.length, 'recording')} to start with, out of the{' '}
                    {recordingCount(card, maxRecordings)} behind {card.event}:
                </span>
            </div>
            <div className="flex w-fit max-w-full flex-col overflow-hidden rounded border border-primary">
                {card.highlights.map((highlight, position) => {
                    const recording = recordingsById.get(highlight.session_id)
                    return (
                        <LemonButton
                            key={highlight.session_id}
                            size="small"
                            fullWidth
                            icon={<IconPlay />}
                            onClick={() => onOpenHighlight(card, highlight.session_id, position)}
                            data-attr="experiment-watch-highlight"
                        >
                            <span className="flex w-full min-w-0 items-center gap-3 text-xs">
                                {/* Fixed width and tabular figures so the durations line up as a
                                    column while the list is still filling in from the playlist. */}
                                <span className="w-16 shrink-0 tabular-nums text-secondary">
                                    {recording ? humanFriendlyDuration(recording.recording_duration) : ''}
                                </span>
                                <span className="w-40 shrink-0 truncate">
                                    {recording?.person ? asDisplay(recording.person) : 'Unknown person'}
                                </span>
                                <span className="truncate text-secondary">{highlight.reason}</span>
                            </span>
                        </LemonButton>
                    )
                })}
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

export function ExperimentBehaviorComparison({
    experiment,
    onWatchRecording,
}: {
    experiment: Experiment
    /** Opens a recording in the playlist below; returns false when nothing could be opened. */
    onWatchRecording: (sessionId: string) => boolean
}): JSX.Element | null {
    const logic = experimentReplayTabLogic({ experiment })
    const {
        behaviorComparisonAvailable,
        behaviorComparisonOpen,
        sessionEventDeltas,
        sessionEventDeltasLoading,
        sessionEventDeltasError,
        selectedWatchCard,
        loadedRecordingsById,
    } = useValues(logic)
    const { selectWatchCard, loadSessionEventDeltas, watchHighlightOpened } = useActions(logic)

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
                <WatchShelves
                    deltas={sessionEventDeltas}
                    // What "no differences yet" is allowed to promise. Read from the status rather
                    // than from end_date, so a state that carries an end date without having
                    // stopped enrolling people cannot reach the past-tense copy.
                    ended={hasEnded(experiment)}
                    selectedCard={selectedWatchCard}
                    onSelect={selectWatchCard}
                    recordingsById={loadedRecordingsById}
                    onOpenHighlight={(card, sessionId, position) => {
                        // Reported only when a recording actually opened: this event is the
                        // feature's success metric, and a click that silently did nothing must
                        // not count toward it.
                        if (onWatchRecording(sessionId)) {
                            watchHighlightOpened(card, position)
                        }
                    }}
                />
            )}
        </div>
    )
}

function WatchShelves({
    deltas,
    ended,
    selectedCard,
    onSelect,
    recordingsById,
    onOpenHighlight,
}: {
    deltas: ExperimentSessionEventDeltaResponseApi
    ended: boolean
    selectedCard: ExperimentWatchCardApi | null
    onSelect: (card: ExperimentWatchCardApi | null) => void
    recordingsById: Map<string, ExperimentReplayRecording>
    onOpenHighlight: (card: ExperimentWatchCardApi, sessionId: string, position: number) => void
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
    const variantOnlyCards = deltas.cards.filter((card) => card.kind === ExperimentWatchCardKindEnumApi.VariantOnly)
    const metricCards = deltas.cards.filter((card) => card.kind === ExperimentWatchCardKindEnumApi.Metric)
    const metricEvents = [...new Set(metricCards.map((card) => card.event))]

    return (
        <div className="flex flex-col gap-3">
            <ShelfCaption deltas={deltas} />
            {/* Said whenever nothing was found, not only when the response is empty: the shelves
                below can be full of metric shortcuts and events a variant renders itself, and a
                reader left to infer "no differences" from their absence reads the surface as
                broken instead. */}
            {behaviorCards.length === 0 && frictionCards.length === 0 && (
                <div className="text-xs text-secondary">
                    {ended
                        ? "No variant showed clearly different behavior in its recorded sessions. Differences small enough to be chance don't get a card."
                        : "No variant shows clearly different behavior in its recorded sessions yet. Differences small enough to be chance don't get a card, so this can change as more people are exposed."}
                </div>
            )}
            <Shelf
                title="Behaves differently"
                cards={behaviorCards}
                selectedCard={selectedCard}
                armKeys={armKeys}
                maxRecordings={deltas.max_card_recordings}
                onSelect={onSelect}
                recordingsById={recordingsById}
                onOpenHighlight={onOpenHighlight}
            />
            <Shelf
                title="Friction"
                cards={frictionCards}
                selectedCard={selectedCard}
                armKeys={armKeys}
                maxRecordings={deltas.max_card_recordings}
                onSelect={onSelect}
                recordingsById={recordingsById}
                onOpenHighlight={onOpenHighlight}
            />
            <Shelf
                title="Only in this variant"
                note="These events don't exist in the other variants, so they show the change is live rather than a difference in what people did."
                cards={variantOnlyCards}
                selectedCard={selectedCard}
                armKeys={armKeys}
                maxRecordings={deltas.max_card_recordings}
                onSelect={onSelect}
                recordingsById={recordingsById}
                onOpenHighlight={onOpenHighlight}
            />
            {metricEvents.length > 0 && (
                <ShelfFrame
                    title="Metrics"
                    note="See your metric events happen. The Results tab measures them."
                    cards={metricCards}
                    selectedCard={selectedCard}
                    recordingsById={recordingsById}
                    maxRecordings={deltas.max_card_recordings}
                    onOpenHighlight={onOpenHighlight}
                >
                    <div className="flex flex-wrap gap-2">
                        {metricEvents.map((event) => {
                            const cards = metricCards.filter((card) => card.event === event)
                            return (
                                <MetricEventCard
                                    key={event}
                                    event={event}
                                    metricName={cards[0].metric_name}
                                    cards={cards}
                                    selectedCard={selectedCard}
                                    maxRecordings={deltas.max_card_recordings}
                                    onSelect={onSelect}
                                />
                            )
                        })}
                    </div>
                </ShelfFrame>
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
    // Named as a length and not only as two dates: the session ceiling can shrink the window to
    // hours on a busy experiment, and "between Aug 8 and Aug 10" reads as the whole run to anyone
    // who doesn't do the subtraction.
    const span = dayjs(deltas.date_from).from(dayjs(deltas.date_to), true)
    const details = [
        'Each variant is compared against the others on which events people did, counting each person once, in the first session they were exposed in. Cards only appear where the difference is too big to be chance, and only with recordings that actually exist.',
        'Page views, autocaptures and the exposure event are never compared, since their names describe a mechanism rather than something a person did.',
        deltas.metric_events.length > 0
            ? `The events this experiment measures (${deltas.metric_events.join(', ')}) can get cards too, but a card never says how a metric moved: the Results tab states that.`
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
                the way metrics do. From about {span} of recorded sessions, between{' '}
                {dayjs(deltas.date_from).format(format)} and {dayjs(deltas.date_to).format(format)}.
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
