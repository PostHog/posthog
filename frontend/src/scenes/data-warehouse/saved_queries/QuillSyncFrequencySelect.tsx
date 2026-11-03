import { IconInfo, IconRabbit, IconTortoise } from '@posthog/icons'
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
    SYNC_FREQUENCY_HELP,
    SyncFrequencySelectProps,
    buildExplanation,
    buildOptions,
    modeDisabledReason,
    unsatisfiableReason,
} from './SyncFrequencySelect'

const PACE_ICON_CLASS = 'shrink-0 text-xl text-muted-foreground'

export function QuillSyncFrequencySelect({
    bounds,
    value,
    onChange,
    loading,
    disabledReason,
    'data-attr': dataAttr,
}: SyncFrequencySelectProps): JSX.Element {
    const options = buildOptions(bounds)
    const explanation = buildExplanation(bounds)
    const modeReason = modeDisabledReason(bounds)
    const reason =
        disabledReason ?? (loading ? 'Saving the new cadence.' : undefined) ?? unsatisfiableReason(bounds) ?? undefined

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
                    value={value && value !== 'never' ? [value] : []}
                    onValueChange={(next: string[]) => next[0] && onChange(next[0] as DataModelingSyncInterval)}
                >
                    {options.map((option) => {
                        const optionReason = reason ?? option.disabledReason
                        return optionReason ? (
                            <ToggleGroupItem key={option.value} value={option.value} disabledReason={optionReason}>
                                {option.label}
                            </ToggleGroupItem>
                        ) : (
                            <Tooltip key={option.value}>
                                <TooltipTrigger render={<ToggleGroupItem value={option.value} />}>
                                    {option.label}
                                </TooltipTrigger>
                                <TooltipContent>{option.tooltip}</TooltipContent>
                            </Tooltip>
                        )
                    })}
                </ToggleGroup>
                <IconTortoise className={PACE_ICON_CLASS} aria-hidden />
            </div>
            {explanation && <FieldDescription className="max-w-prose">{explanation}</FieldDescription>}
        </Field>
    )
}
