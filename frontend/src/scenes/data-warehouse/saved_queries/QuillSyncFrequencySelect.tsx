import { IconInfo, IconPinFilled, IconRabbit, IconTortoise, IconX } from '@posthog/icons'
import {
    Button,
    Field,
    FieldDescription,
    FieldLabel,
    Spinner,
    Text,
    ToggleGroup,
    ToggleGroupItem,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { DataModelingSyncInterval } from '~/types'

import {
    CADENCE_SEGMENTS,
    CadenceNote,
    SYNC_FREQUENCY_HELP,
    SyncFrequencySelectProps,
    UPSTREAM_RULE,
    pinnedSegmentTooltip,
    syncFrequencyState,
} from './SyncFrequencySelect'

const PACE_ICON_CLASS = 'shrink-0 text-xl text-muted-foreground'

function QuillCadenceNote({ note }: { note: CadenceNote }): JSX.Element {
    if (!note.upstreamRule) {
        return <FieldDescription className="max-w-prose">{note.text}</FieldDescription>
    }
    return (
        <FieldDescription className="max-w-prose">
            <span>{note.text}</span>{' '}
            <Tooltip>
                <TooltipTrigger
                    render={<span tabIndex={0} className="inline-flex align-text-bottom" aria-label={UPSTREAM_RULE} />}
                >
                    <IconInfo />
                </TooltipTrigger>
                <TooltipContent className="max-w-80">{UPSTREAM_RULE}</TooltipContent>
            </Tooltip>
        </FieldDescription>
    )
}

function PinnedSegmentLabel({
    cadence,
    canUnpin,
}: {
    cadence: DataModelingSyncInterval
    canUnpin: boolean
}): JSX.Element {
    return (
        <span className="inline-flex items-center gap-0.5">
            {CADENCE_SEGMENTS[cadence]}
            <IconPinFilled className={canUnpin ? 'group-hover/pinned:hidden' : undefined} aria-hidden />
            {canUnpin && <IconX className="hidden group-hover/pinned:inline" aria-hidden />}
        </span>
    )
}

export function QuillSyncFrequencySelect({
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
            <Text size="xs" variant="muted" className="max-w-prose" data-attr={dataAttr}>
                {modeReason}
            </Text>
        )
    }

    return (
        <Field className="items-start" data-attr={dataAttr}>
            <FieldLabel className="flex items-center gap-1">
                Refresh every
                <Tooltip>
                    <TooltipTrigger delay={0} render={<Button size="icon-xs" aria-label="About refresh frequency" />}>
                        <IconInfo />
                    </TooltipTrigger>
                    <TooltipContent className="max-w-80">{SYNC_FREQUENCY_HELP}</TooltipContent>
                </Tooltip>
                {loading && (
                    <span className="inline-flex items-center gap-1 font-normal text-muted-foreground" role="status">
                        <Spinner /> Saving…
                    </span>
                )}
            </FieldLabel>
            <div className="flex flex-wrap items-center gap-2">
                <IconRabbit className={PACE_ICON_CLASS} aria-hidden />
                <ToggleGroup
                    variant="outline"
                    aria-label="Refresh every"
                    value={selected ? [selected] : []}
                    onValueChange={(next: string[]) => {
                        const picked = next[0] as DataModelingSyncInterval | undefined
                        if (picked && picked !== selected) {
                            onChange(picked)
                        } else if (!picked && canUnpin) {
                            onUnpin?.()
                        }
                    }}
                >
                    {options.map((option) => {
                        const optionReason = reason ?? option.disabledReason
                        const pinnedHere = !!pin?.pinned && option.value === selected
                        if (optionReason) {
                            return (
                                <ToggleGroupItem key={option.value} value={option.value} disabledReason={optionReason}>
                                    {option.label}
                                </ToggleGroupItem>
                            )
                        }
                        return (
                            <Tooltip key={option.value}>
                                <TooltipTrigger
                                    render={
                                        <ToggleGroupItem
                                            value={option.value}
                                            className={pinnedHere ? 'group/pinned' : undefined}
                                            data-attr={pinnedHere && canUnpin ? 'sync-frequency-unpin' : undefined}
                                        />
                                    }
                                >
                                    {pinnedHere ? (
                                        <PinnedSegmentLabel cadence={option.value} canUnpin={canUnpin} />
                                    ) : (
                                        option.label
                                    )}
                                </TooltipTrigger>
                                <TooltipContent>
                                    {pinnedHere ? pinnedSegmentTooltip(option.value, canUnpin) : option.tooltip}
                                </TooltipContent>
                            </Tooltip>
                        )
                    })}
                </ToggleGroup>
                <IconTortoise className={PACE_ICON_CLASS} aria-hidden />
            </div>
            {notes.map((note) => (
                <QuillCadenceNote key={note.key} note={note} />
            ))}
            {explanation && <FieldDescription className="max-w-prose">{explanation}</FieldDescription>}
        </Field>
    )
}
