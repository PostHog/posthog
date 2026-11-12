import { IconInfo, IconPinFilled, IconRabbit, IconTortoise, IconX } from '@posthog/icons'
import { LemonLabel, LemonSegmentedButton, LemonSegmentedButtonOption, Spinner } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { DataModelingSyncInterval } from '~/types'

import { NodePinBlockerApi, NodePinDelayApi } from 'products/data_modeling/frontend/generated/api.schemas'
import { SyncFrequencyBoundsApi } from 'products/data_warehouse/frontend/generated/api.schemas'

export type SyncFrequencyValue = DataModelingSyncInterval | 'never'

/**
 * Interval wording ("refresh every X"), which the bounds are what make truthful: a view may only be
 * set at or below its consumers' cadence, so the value picked here is the cadence that runs, not a
 * request the scheduler quietly tightens. The bar carries the wording once in its label, so each
 * segment only has to say which duration it is.
 */
/** How a cadence is spoken after "every", so every surface says "every 6 hours" the same way. */
export const CADENCE_LABELS: Record<DataModelingSyncInterval, string> = {
    '15min': '15 minutes',
    '30min': '30 minutes',
    '1hour': '1 hour',
    '6hour': '6 hours',
    '12hour': '12 hours',
    '24hour': '1 day',
    '7day': '7 days',
    '30day': '30 days',
}

export const CADENCE_SEGMENTS: Record<DataModelingSyncInterval, string> = {
    '15min': '15m',
    '30min': '30m',
    '1hour': '1h',
    '6hour': '6h',
    '12hour': '12h',
    '24hour': '1d',
    '7day': '7d',
    '30day': '30d',
}

export const SYNC_FREQUENCY_HELP =
    'How often this model refreshes. It cannot refresh more often than its upstream sources sync, or less often than downstream models and endpoints need it. Hover over an unavailable frequency to see what limits it.'

const PLAN_UPGRADE_REASONS: Partial<Record<DataModelingSyncInterval, string>> = {
    '15min': 'Needs a Boost, Teams, Scale, or Enterprise add-on',
    '30min': 'Needs a paid plan',
}

const ORDERED_CADENCES = Object.keys(CADENCE_LABELS) as DataModelingSyncInterval[]

/**
 * Decorative, so `aria-hidden`: they only restate which way the bar runs, which the segment labels
 * already say outright.
 */
const PACE_ICON_CLASS = 'text-xl text-secondary shrink-0'

/**
 * Why the cadence controls are read-only, for the modes where cadence is not this view's to set.
 *
 * `no_node` belongs here despite having no bounds to show: the missing-node guard refuses every
 * cadence write, so a live control only buys a 400. The reason carries the way out instead.
 */
const MODE_DISABLED_REASONS: Record<string, string> = {
    managed_viewset: 'PostHog manages this view, including how often it refreshes.',
    no_node: 'This view is not set up for scheduled refreshes yet. Save it again, then pick a cadence.',
}

/** Why the view's frequency mode locks its cadence controls, or null where the mode allows them. */
export function modeDisabledReason(bounds?: SyncFrequencyBoundsApi | null): string | null {
    return (bounds && MODE_DISABLED_REASONS[bounds.frequency_mode]) || null
}

export interface CadencePin {
    /** True when the pin is saved or the next save writes it. */
    pinned: boolean
    /** True when the next save changes the pin. */
    pending: boolean
    /** Downstream views that refresh more often than the pinned cadence. */
    delayed: NodePinDelayApi[]
    /** Per cadence, the downstream view a pin that slow would leave unable to meet its own cadence. */
    blockedBy: Partial<Record<string, NodePinBlockerApi>>
    /** Per cadence, the downstream views that would read older data if this view were pinned to it. */
    delaysBy: Partial<Record<string, NodePinDelayApi[]>>
    /** Per cadence, the cadence this view runs at once unpinned, which only the server can work out because other pins stop demand. */
    unpinnedBy: Partial<Record<string, DataModelingSyncInterval>>
}

export interface SyncFrequencySelectProps {
    /** Bounds from the saved query. Undefined while loading, or on surfaces that don't fetch them. */
    bounds?: SyncFrequencyBoundsApi | null
    /** A paused view ("never") leaves the bar with nothing selected, since pausing is not a cadence. */
    value: SyncFrequencyValue | null
    onChange: (value: DataModelingSyncInterval) => void
    /** Locks the bar while a change is in flight, so one click can't queue eight cadence writes. */
    loading?: boolean
    /** Takes precedence over the mode's own reason, so access checks win over scheduling ones. */
    disabledReason?: string
    'data-attr'?: string
    /** Set when the view has a DAG node, so a cadence slower than a downstream view can pin instead of being refused. */
    pin?: CadencePin | null
    onUnpin?: () => void
}

/**
 * A cadence picker that offers only what the scheduler will honor, and names what withholds the rest.
 *
 * Without bounds it degrades to every cadence, which is what teams whose backend accepts any of them
 * should see.
 */
export function SyncFrequencySelect({
    bounds,
    value,
    onChange,
    loading,
    disabledReason,
    'data-attr': dataAttr,
    pin,
    onUnpin,
}: SyncFrequencySelectProps): JSX.Element {
    const { selected, options, canUnpin, modeReason, reason, notes, explanation } = syncFrequencyState({
        bounds,
        value,
        loading,
        disabledReason,
        pin,
        onUnpin,
    })

    if (modeReason) {
        return (
            <span className="text-xs text-secondary max-w-prose" data-attr={dataAttr}>
                {modeReason}
            </span>
        )
    }

    return (
        <div className="flex flex-col gap-1 items-start" data-attr={dataAttr}>
            <LemonLabel info={SYNC_FREQUENCY_HELP}>
                Refresh every
                {loading && (
                    <span className="inline-flex items-center gap-1 text-secondary font-normal" role="status">
                        <Spinner /> Saving…
                    </span>
                )}
            </LemonLabel>
            <div className="flex items-center gap-2">
                <IconRabbit className={PACE_ICON_CLASS} aria-hidden />
                <LemonSegmentedButton<DataModelingSyncInterval>
                    size="small"
                    value={selected}
                    onChange={(next) => {
                        // Compare against what the bar shows: a saved cadence the scheduler overrides shows
                        // the inherited one, and clicking the saved one again is how the view gets pinned to it.
                        if (next !== selected) {
                            onChange(next)
                        } else if (canUnpin) {
                            onUnpin?.()
                        }
                    }}
                    options={pin?.pinned ? withPinnedSegment(options, selected, { canUnpin }) : options}
                    disabledReason={reason}
                />
                <IconTortoise className={PACE_ICON_CLASS} aria-hidden />
            </div>
            <CadenceNotes notes={notes} explanation={explanation} />
        </div>
    )
}

export interface SyncFrequencyState {
    selected: DataModelingSyncInterval | undefined
    options: LemonSegmentedButtonOption<DataModelingSyncInterval>[]
    canUnpin: boolean
    modeReason: string | null
    reason: string | undefined
    notes: CadenceNote[]
    explanation: string | null
}

export function syncFrequencyState({
    bounds,
    value,
    loading,
    disabledReason,
    pin,
    onUnpin,
}: Omit<SyncFrequencySelectProps, 'onChange' | 'data-attr'>): SyncFrequencyState {
    const unpinning = pendingUnpin(pin, value)
    const inherited = pin?.pinned || unpinning ? null : inheritedCadence(bounds, value)
    const selected = unpinning?.cadence ?? inherited?.cadence ?? savedCadence(value)
    const options = buildOptions(bounds, {
        canPin: !!pin,
        pinned: !!pin?.pinned,
        pinBlockedBy: pin?.blockedBy,
        pinDelays: pin?.delaysBy,
        unpinnedBy: pin?.unpinnedBy,
    })
    const canUnpin = !!pin?.pinned && !pin.pending && !!onUnpin
    const modeReason = modeDisabledReason(bounds)
    // A pin can make a cadence selectable that the bounds alone refuse, so the bar is only dead when its own options are.
    const nothingSelectable = options.every((option) => option.disabledReason)
    const reason = barDisabledReason({ disabledReason, loading, nothingSelectable, bounds, modeReason })
    return {
        selected,
        options,
        canUnpin,
        modeReason,
        reason,
        notes: loading
            ? []
            : cadenceNotes({
                  pin,
                  selected,
                  unpinning,
                  inherited,
                  speedUp: speedUpFor(bounds, value),
              }),
        // The inherited note already names the downstream view, so the ceiling sentence would repeat it.
        // With a pin on offer, a downstream view no longer caps how slow this view can go.
        explanation: buildExplanation(bounds, { omitCeiling: !!inherited || !!pin }),
    }
}

function savedCadence(value: SyncFrequencyValue | null): DataModelingSyncInterval | undefined {
    return value && value !== 'never' ? value : undefined
}

function pendingUnpin(
    pin: CadencePin | null | undefined,
    value: SyncFrequencyValue | null
): ReturnType<typeof unpinnedCadence> {
    return pin && !pin.pinned && pin.pending ? unpinnedCadence(pin.unpinnedBy, pin.delaysBy, value) : null
}

function speedUpFor(
    bounds: SyncFrequencyBoundsApi | null | undefined,
    value: SyncFrequencyValue | null
): string | null {
    const saved = savedCadence(value)
    return saved ? speedUpWarning(bounds, saved) : null
}

function barDisabledReason({
    disabledReason,
    loading,
    nothingSelectable,
    bounds,
    modeReason,
}: {
    disabledReason?: string
    loading?: boolean
    nothingSelectable: boolean
    bounds: SyncFrequencyBoundsApi | null | undefined
    modeReason: string | null
}): string | undefined {
    return (
        disabledReason ??
        (loading ? 'Saving the new cadence.' : undefined) ??
        (nothingSelectable ? unsatisfiableReason(bounds) : null) ??
        modeReason ??
        undefined
    )
}

export interface CadenceNote {
    key: string
    text: string
    /** True when the note leans on the upstream rule, so it links to the explanation. */
    upstreamRule: boolean
}

/** The notes under the bar, in the order they apply: what the pin does, what an unpin does, what the scheduler overrides, what a pick speeds up. */
function cadenceNotes({
    pin,
    selected,
    unpinning,
    inherited,
    speedUp,
}: {
    pin?: CadencePin | null
    selected?: DataModelingSyncInterval
    unpinning: { note: string } | null
    inherited: { note: string } | null
    speedUp: string | null
}): CadenceNote[] {
    const notes: (CadenceNote | null)[] = [
        pin?.pinned && selected
            ? { key: 'pin', text: pinNote(selected, pin.delayed, { pending: pin.pending }), upstreamRule: false }
            : null,
        unpinning ? { key: 'unpinning', text: unpinning.note, upstreamRule: true } : null,
        inherited ? { key: 'inherited', text: inherited.note, upstreamRule: true } : null,
        speedUp ? { key: 'speed-up', text: speedUp, upstreamRule: true } : null,
    ]
    return notes.filter((note): note is CadenceNote => !!note)
}

function CadenceNotes({ notes, explanation }: { notes: CadenceNote[]; explanation: string | null }): JSX.Element {
    return (
        <>
            {notes.map((note) => (
                <span key={note.key} className="text-xs text-secondary max-w-prose">
                    {note.upstreamRule ? <WithUpstreamRule text={note.text} /> : note.text}
                </span>
            ))}
            {explanation && <span className="text-xs text-secondary max-w-prose">{explanation}</span>}
        </>
    )
}

/**
 * What else a cadence changes, or null when it only changes this view.
 *
 * A view can't be fresher than its inputs, so a slower upstream view runs at this cadence for as long
 * as this view does. Its saved setting is left alone.
 */
export function speedUpWarning(
    bounds: SyncFrequencyBoundsApi | null | undefined,
    cadence: DataModelingSyncInterval
): string | null {
    const option = bounds?.options.find((candidate) => candidate.cadence === cadence)
    if (!option || (!option.speeds_up?.length && !option.speeds_up_withheld)) {
        return null
    }

    const named = option.speeds_up.map((view) => view.name).filter(Boolean)
    const plural = named.length > 1 || option.speeds_up_withheld || !named.length
    const subject = !named.length
        ? 'Some upstream views'
        : `${plural ? 'Upstream views' : 'Upstream view'} ${named.join(', ')}${option.speeds_up_withheld ? ' and others' : ''}`
    return `${subject} also ${plural ? 'refresh' : 'refreshes'} every ${CADENCE_LABELS[cadence]} to keep up with this view.`
}

export function unpinnedCadence(
    unpinnedBy: Partial<Record<string, DataModelingSyncInterval>>,
    delaysBy: Partial<Record<string, { name: string }[]>>,
    value: SyncFrequencyValue | null
): { cadence: DataModelingSyncInterval; note: string } | null {
    if (!value || value === 'never') {
        return null
    }
    const cadence = unpinnedBy[value]
    if (!cadence || cadence === value) {
        return null
    }
    // The names only describe who reads older data under the pin. The cadence itself comes from the server.
    const delayed = (delaysBy[value] ?? []).map((view) => view.name)
    const who = !delayed.length
        ? 'downstream views'
        : delayed.length > 1
          ? `downstream views ${delayed.join(', ')}`
          : `downstream view ${delayed[0]}`
    return {
        cadence,
        note: `Once you save, this view refreshes every ${CADENCE_LABELS[cadence]} to keep up with ${who}.`,
    }
}

/**
 * True when the view, once unpinned, would run faster than this cadence because a downstream view
 * asks for it, which is when holding the cadence takes a pin. Read from the node bounds, which are
 * calculated without this view's own pin, so a pinned view still tells.
 */
export function needsPin(unpinnedBy: CadencePin['unpinnedBy'] | undefined, cadence: SyncFrequencyValue): boolean {
    if (cadence === 'never') {
        return false
    }
    const unpinned = unpinnedBy?.[cadence]
    return !!unpinned && ORDERED_CADENCES.indexOf(unpinned) < ORDERED_CADENCES.indexOf(cadence)
}

/** What a pin means for the downstream views, so nobody pins without seeing who reads older data. */
export function pinNote(
    cadence: DataModelingSyncInterval,
    delayed: NodePinDelayApi[],
    { pending }: { pending: boolean }
): string {
    const every = CADENCE_LABELS[cadence]
    const lead = pending ? `Saving pins this view to refresh every ${every}` : `Pinned to refresh every ${every}`
    if (!delayed.length) {
        return `${lead}, even when downstream views need fresher data.`
    }
    const plural = delayed.length > 1
    return (
        `${lead}. ${plural ? 'Downstream views' : 'Downstream view'} ${delayed.map((view) => view.name).join(', ')} ` +
        `${plural ? 'refresh' : 'refreshes'} more often, so ${plural ? 'they read' : 'it reads'} data up to ${every} old.`
    )
}

export const UPSTREAM_RULE =
    "A view can't be fresher than the data it reads, so upstream views refresh at least as often as the downstream views built on them."

function WithUpstreamRule({ text }: { text: string }): JSX.Element {
    return (
        <>
            <span>{text}</span>{' '}
            <Tooltip title={UPSTREAM_RULE}>
                <IconInfo className="inline align-text-bottom text-sm" aria-label={UPSTREAM_RULE} />
            </Tooltip>
        </>
    )
}

/**
 * The cadence a view actually runs at when its saved setting is slower than a consumer needs.
 *
 * The scheduler runs a view at the finest cadence among itself and its consumers, so the saved
 * setting is a lower bound on freshness, not the schedule. Options arrive coarsest-last, so the last
 * allowed one is the consumer ceiling.
 */
export function inheritedCadence(
    bounds: SyncFrequencyBoundsApi | null | undefined,
    value: SyncFrequencyValue | null
): { cadence: DataModelingSyncInterval; note: string } | null {
    if (!bounds || !value || value === 'never') {
        return null
    }
    const saved = bounds.options.find((option) => option.cadence === value)
    const allowed = bounds.options.filter((option) => option.allowed)
    if (!saved || saved.allowed || saved.blocked_by !== 'consumer' || !allowed.length) {
        return null
    }

    const cadence = allowed[allowed.length - 1].cadence as DataModelingSyncInterval
    const consumer = bounds.ceiling?.blocker?.name
    return {
        cadence,
        note:
            `Refreshes every ${CADENCE_LABELS[cadence]} to keep up with ${consumer ? `downstream view ${consumer}` : 'a downstream view'}. ` +
            `Your ${CADENCE_LABELS[value]} setting applies again if downstream views refresh less often.`,
    }
}

export function buildOptions(
    bounds?: SyncFrequencyBoundsApi | null,
    {
        canPin = false,
        pinned = false,
        pinBlockedBy = {},
        pinDelays = {},
        unpinnedBy,
    }: {
        canPin?: boolean
        pinned?: boolean
        pinBlockedBy?: Partial<Record<string, NodePinBlockerApi>>
        pinDelays?: Partial<Record<string, { name: string }[]>>
        unpinnedBy?: CadencePin['unpinnedBy']
    } = {}
): LemonSegmentedButtonOption<DataModelingSyncInterval>[] {
    if (!bounds?.options.length) {
        return ORDERED_CADENCES.map((cadence) => segment(cadence))
    }

    const pinContext = { canPin, pinned, pinBlockedBy, pinDelays, unpinnedBy }
    return bounds.options.map((option) => {
        const cadence = option.cadence as DataModelingSyncInterval
        // A pin holds a view back from its consumers, and the plan floor applies to it all the same.
        if (option.blocked_by === 'plan') {
            return { ...segment(cadence), disabledReason: blockedReason(option, bounds) }
        }
        return {
            ...segment(cadence),
            ...(pinOptionState(option, cadence, pinContext) ?? {
                disabledReason: option.allowed ? undefined : blockedReason(option, bounds),
            }),
        }
    })
}

interface PinContext {
    canPin: boolean
    pinned: boolean
    pinBlockedBy: Partial<Record<string, NodePinBlockerApi>>
    pinDelays: Partial<Record<string, { name: string }[]>>
    unpinnedBy?: CadencePin['unpinnedBy']
}

function pinOptionState(
    option: SyncFrequencyBoundsApi['options'][number],
    cadence: DataModelingSyncInterval,
    { canPin, pinned, pinBlockedBy, pinDelays, unpinnedBy }: PinContext
): Pick<LemonSegmentedButtonOption<DataModelingSyncInterval>, 'disabledReason' | 'tooltip'> | null {
    if (!canPin) {
        return null
    }
    const stranded = pinBlockedBy[cadence]
    const wantsPin = needsPin(unpinnedBy, cadence)
    // A pinned view has no consumer ceiling, so the bounds alone never mark a slower cadence as needing a pin.
    if (stranded && (pinned || wantsPin)) {
        return {
            disabledReason: `Can't pin: ${stranded.name ? `downstream view ${stranded.name}` : 'a downstream view'} reads fresh data only through this view`,
        }
    }
    if (wantsPin) {
        const delayed = pinDelays[cadence]?.map((view) => view.name) ?? []
        const names = delayed.length ? delayed : option.blocker ? [option.blocker.name] : []
        return { tooltip: pinTooltip(cadence, names) }
    }
    return null
}

function pinTooltip(cadence: DataModelingSyncInterval, names: string[]): string {
    const who =
        names.length > 1
            ? `Downstream views ${names.join(', ')} refresh`
            : names.length === 1
              ? `Downstream view ${names[0]} refreshes`
              : 'A downstream view refreshes'
    return `Pin this view to every ${CADENCE_LABELS[cadence]}. ${who} more often and will read older data from it.`
}

/**
 * The pinned cadence carries a pin, which turns into an unpin cross while the segment is hovered.
 * Clicking the selected segment unpins, so there is no button nested inside the segment's button.
 */
function pinnedSegment(
    option: LemonSegmentedButtonOption<DataModelingSyncInterval>,
    { canUnpin }: { canUnpin: boolean }
): LemonSegmentedButtonOption<DataModelingSyncInterval> {
    const cadence = option.value
    return {
        ...option,
        disabledReason: canUnpin ? undefined : option.disabledReason,
        label: (
            <span className="inline-flex items-center gap-0.5">
                {CADENCE_SEGMENTS[cadence]}
                <IconPinFilled className={canUnpin ? '[li:hover_&]:hidden' : undefined} aria-hidden />
                {canUnpin && <IconX className="hidden [li:hover_&]:inline" aria-hidden />}
            </span>
        ),
        tooltip: pinnedSegmentTooltip(cadence, canUnpin),
        'data-attr': canUnpin ? 'sync-frequency-unpin' : option['data-attr'],
    }
}

export function pinnedSegmentTooltip(cadence: DataModelingSyncInterval, canUnpin: boolean): string {
    return canUnpin
        ? `Pinned to every ${CADENCE_LABELS[cadence]}. Click to unpin.`
        : `Pinned to every ${CADENCE_LABELS[cadence]} once you save.`
}

export function withPinnedSegment(
    options: LemonSegmentedButtonOption<DataModelingSyncInterval>[],
    selected: DataModelingSyncInterval | undefined,
    { canUnpin }: { canUnpin: boolean }
): LemonSegmentedButtonOption<DataModelingSyncInterval>[] {
    return options.map((option) => (option.value === selected ? pinnedSegment(option, { canUnpin }) : option))
}

/** Abbreviated on the bar, spelled out on hover, so eight segments stay readable at one glance. */
function segment(cadence: DataModelingSyncInterval): LemonSegmentedButtonOption<DataModelingSyncInterval> {
    return { value: cadence, label: CADENCE_SEGMENTS[cadence], tooltip: `Every ${CADENCE_LABELS[cadence]}` }
}

/**
 * Terse on purpose: the line under the bar already spells out both bounds, so a segment only has to
 * say which direction it falls outside and who holds that end.
 *
 * A blocker the caller may not read arrives as `null`, so keep the direction and drop the name
 * rather than falling through to something that says neither.
 */
function blockedReason(option: SyncFrequencyBoundsApi['options'][number], bounds: SyncFrequencyBoundsApi): string {
    const name = option.blocker?.name
    if (option.blocked_by === 'source' && bounds.floor) {
        return name ? `More often than upstream source ${name} syncs` : 'More often than the upstream sources sync'
    }
    if (option.blocked_by === 'plan') {
        return PLAN_UPGRADE_REASONS[option.cadence as DataModelingSyncInterval] ?? 'More often than your plan allows'
    }
    if (option.blocked_by === 'consumer' && bounds.ceiling) {
        return name ? `Too slow for downstream view ${name}` : 'Too slow for a downstream view'
    }
    return 'Not available for this view'
}

/**
 * Why no cadence at all can be picked, when a view's lineage leaves an empty range.
 *
 * Not the same as having no bounds: an empty `options` list means unbounded, while options that are
 * all blocked mean a floor above the ceiling, which the backend refuses whatever gets submitted.
 * Callers offering a Materialize action must gate it on this, since there is nothing to fall back to.
 */
export function unsatisfiableReason(bounds?: SyncFrequencyBoundsApi | null): string | null {
    if (!bounds?.options.length || bounds.options.some((option) => option.allowed)) {
        return null
    }

    const sourceName = bounds.floor?.blocker?.name
    const consumerName = bounds.ceiling?.blocker?.name
    const source = sourceName ? `upstream source ${sourceName}` : 'an upstream source'
    const consumer = consumerName ? `downstream view ${consumerName}` : 'a downstream view or endpoint'
    if (bounds.floor && bounds.ceiling) {
        return (
            `No cadence works here: ${source} only syncs every ${bounds.floor.label}, ` +
            `but ${consumer} refreshes every ${bounds.ceiling.label}. ` +
            `Slow down ${consumer} or speed up ${source}.`
        )
    }
    if (bounds.floor) {
        return (
            `No cadence works here: ${source} only syncs every ${bounds.floor.label}, ` +
            `less often than anything this can refresh at. Speed up ${source} first.`
        )
    }
    if (bounds.ceiling) {
        return (
            `No cadence works here: ${consumer} refreshes every ${bounds.ceiling.label}, ` +
            `more often than anything this can refresh at. Slow down ${consumer} first.`
        )
    }
    return 'No cadence works here.'
}

/**
 * A cadence to start a never-materialized view on, given what its lineage allows.
 *
 * `preferred` is a fixed default, so on a view with a sub-daily consumer it names a cadence the
 * backend refuses — the picker would open on a greyed-out row and Materialize would 400. Falls back
 * to the coarsest allowed cadence no coarser than `preferred`, so a first run stays as cheap as the
 * lineage permits. When nothing is allowed there is no such fallback, so it returns `preferred`
 * unchanged and `unsatisfiableReason` is what keeps the action out of reach.
 */
export function defaultCadenceWithin(
    bounds: SyncFrequencyBoundsApi | null | undefined,
    preferred: DataModelingSyncInterval
): DataModelingSyncInterval {
    const allowed = (bounds?.options ?? [])
        .filter((option) => option.allowed)
        .map((option) => option.cadence as DataModelingSyncInterval)
    if (!allowed.length || allowed.includes(preferred)) {
        return preferred
    }

    const rank = (cadence: DataModelingSyncInterval): number => ORDERED_CADENCES.indexOf(cadence)
    const upToPreferred = allowed.filter((cadence) => rank(cadence) <= rank(preferred))
    const pool = upToPreferred.length ? upToPreferred : allowed
    return pool.reduce((coarsest, cadence) => (rank(cadence) > rank(coarsest) ? cadence : coarsest))
}

export function buildExplanation(
    bounds?: SyncFrequencyBoundsApi | null,
    { omitCeiling = false }: { omitCeiling?: boolean } = {}
): string | null {
    if (!bounds || bounds.frequency_mode !== 'tiered') {
        return null
    }
    const parts = [
        boundsSentence(bounds.floor, omitCeiling ? null : bounds.ceiling),
        bestEffortSentence(bounds),
    ].filter((part): part is string => !!part)
    return parts.length ? parts.join(' ') : null
}

function boundsSentence(
    floor: SyncFrequencyBoundsApi['floor'],
    ceiling: SyncFrequencyBoundsApi['ceiling'] | null
): string | null {
    // A withheld blocker still has to hold its slot in the sentence, and the two slots read
    // differently: one opens a sentence, one sits mid-clause.
    const floorName = floor?.blocker?.name ? `Upstream source ${floor.blocker.name}` : 'An upstream source'
    const ceilingLead = ceiling?.blocker?.name ? `Downstream view ${ceiling.blocker.name}` : 'A downstream view'
    const ceilingMid = ceiling?.blocker?.name ? `downstream view ${ceiling.blocker.name}` : 'a downstream view'

    if (floor && ceiling) {
        return (
            `Pick between ${floor.label} and ${ceiling.label}. ` +
            `${floorName} syncs every ${floor.label}, ` +
            `and ${ceilingMid} refreshes every ${ceiling.label}.`
        )
    }
    if (floor) {
        return `${floorName} syncs every ${floor.label}, so this can't refresh more often.`
    }
    if (ceiling) {
        return `${ceilingLead} refreshes every ${ceiling.label}, so this can't refresh less often.`
    }
    return null
}

function bestEffortSentence(bounds: SyncFrequencyBoundsApi): string | null {
    const named = bounds.best_effort_sources.map((source) => source.name).filter(Boolean)
    if (!named.length && !bounds.best_effort_sources_withheld) {
        return null
    }
    const subject = named.length
        ? `${named.join(', ')}${bounds.best_effort_sources_withheld ? ' and other sources upstream' : ''}`
        : 'Some sources upstream'
    const plural = named.length > 1 || bounds.best_effort_sources_withheld || !named.length
    return `${subject} ${plural ? 'have' : 'has'} no sync schedule, so refreshing more often won't make that data any newer.`
}
