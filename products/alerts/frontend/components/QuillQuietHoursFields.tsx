import { useId } from 'react'

import { IconTrash } from '@posthog/icons'
import {
    Button,
    Checkbox,
    Field,
    FieldContent,
    FieldDescription,
    FieldLabel,
    Input,
    Item,
    ItemContent,
    ItemDescription,
    Text,
} from '@posthog/quill'

import { MAX_BLOCKED_WINDOWS } from 'products/alerts/frontend/logic/scheduleRestrictionValidation'
import type { BlockedWindow } from 'products/alerts/frontend/types'

import { QuietHoursFieldsProps } from './QuietHoursFields'
import { QuillQuietHoursDayTimeline } from './QuillQuietHoursDayTimeline'
import { normalizeTimeInput, useQuietHoursFieldsState } from './useQuietHoursFieldsState'

export function QuillQuietHoursFields({
    scheduleRestriction,
    cadenceMinutes,
    coarseIntervalLabel,
    teamTimezone,
    onChange,
}: QuietHoursFieldsProps): JSX.Element {
    const checkboxId = useId()
    const {
        enabled,
        windows,
        toggleEnabled,
        updateRow,
        removeRow,
        addRow,
        applyOvernightPreset,
        highFrequencySlotPreview,
        quietIssue,
        atWindowLimit,
        addWindowButtonLabel,
    } = useQuietHoursFieldsState({ scheduleRestriction, cadenceMinutes, teamTimezone, onChange })

    return (
        <div className="flex flex-col gap-3">
            <Field orientation="horizontal">
                <Checkbox
                    id={checkboxId}
                    checked={enabled}
                    onCheckedChange={(checked: boolean) => toggleEnabled(checked)}
                    data-attr="alertForm-quiet-hours-enabled"
                />
                <FieldContent>
                    <FieldLabel htmlFor={checkboxId}>Quiet hours</FieldLabel>
                    <FieldDescription>
                        Alerts won't run during these hours in your project timezone. A check that would land in quiet
                        hours is deferred to the next allowed time.
                    </FieldDescription>
                </FieldContent>
            </Field>
            {enabled ? (
                <>
                    {coarseIntervalLabel ? (
                        <Item tone="info" size="sm">
                            <ItemContent>
                                <ItemDescription>
                                    If a scheduled run would fall during quiet hours, it runs at the next allowed time
                                    in that same day or cycle instead of waiting until the next {coarseIntervalLabel}.
                                </ItemDescription>
                            </ItemContent>
                        </Item>
                    ) : null}
                    <div className="flex flex-wrap gap-2">
                        <Button variant="outline" onClick={applyOvernightPreset}>
                            Preset: overnight (10 PM to 7 AM)
                        </Button>
                    </div>
                    {highFrequencySlotPreview ? (
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            For {highFrequencySlotPreview.cadenceLabel} alerts we schedule about one check every{' '}
                            {highFrequencySlotPreview.intervalLabel}. Roughly {highFrequencySlotPreview.slotApprox} of
                            the next {highFrequencySlotPreview.totalSlots} slots would still run outside quiet hours.
                        </Text>
                    ) : null}
                    {quietIssue ? (
                        <Item tone="destructive" size="sm">
                            <ItemContent>
                                <ItemDescription>{quietIssue.message}</ItemDescription>
                            </ItemContent>
                        </Item>
                    ) : null}
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                        {windows.map((row: BlockedWindow, index: number) => {
                            const invalid = quietIssue?.kind === 'row' && quietIssue.index === index

                            return (
                                // Index-only key: times change while typing; including start/end remounts inputs and drops focus.
                                <div key={index} className="flex min-w-0 flex-wrap items-center gap-2">
                                    <Input
                                        type="time"
                                        step={60}
                                        value={row.start}
                                        className="w-auto"
                                        aria-invalid={invalid || undefined}
                                        onChange={(event) => updateRow(index, 'start', event.target.value)}
                                        onBlur={(event) =>
                                            updateRow(index, 'start', normalizeTimeInput(event.currentTarget.value))
                                        }
                                        aria-label={`Quiet hours period ${index + 1} start time`}
                                        data-attr={`alertForm-quiet-start-${index}`}
                                    />
                                    <Text size="xs" variant="muted" render={<span />}>
                                        to
                                    </Text>
                                    <Input
                                        type="time"
                                        step={60}
                                        value={row.end}
                                        className="w-auto"
                                        aria-invalid={invalid || undefined}
                                        onChange={(event) => updateRow(index, 'end', event.target.value)}
                                        onBlur={(event) =>
                                            updateRow(index, 'end', normalizeTimeInput(event.currentTarget.value))
                                        }
                                        aria-label={`Quiet hours period ${index + 1} end time`}
                                        data-attr={`alertForm-quiet-end-${index}`}
                                    />
                                    <Button
                                        variant="destructive-outline"
                                        size="icon"
                                        onClick={() => removeRow(index)}
                                        aria-label={`Remove quiet hours period ${index + 1}`}
                                        tooltip={`Remove quiet hours period ${index + 1}`}
                                        data-attr={`alertForm-quiet-remove-${index}`}
                                    >
                                        <IconTrash />
                                    </Button>
                                </div>
                            )
                        })}
                    </div>
                    <div>
                        <Button
                            variant="outline"
                            onClick={addRow}
                            disabledReason={
                                atWindowLimit
                                    ? `Each alert can use up to ${MAX_BLOCKED_WINDOWS} quiet hour periods. Remove one to add another.`
                                    : undefined
                            }
                            data-attr="alertForm-quiet-add-period"
                        >
                            {addWindowButtonLabel}
                        </Button>
                    </div>
                    {!quietIssue && windows.length > 0 ? <QuillQuietHoursDayTimeline windows={windows} /> : null}
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        We will not evaluate this alert during these hours. If a scheduled run falls in a window, we run
                        it when the window ends.
                    </Text>
                </>
            ) : null}
        </div>
    )
}
