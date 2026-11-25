import { type FocusEvent } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCheckbox, LemonInput } from '@posthog/lemon-ui'

import { MAX_BLOCKED_WINDOWS } from 'products/alerts/frontend/logic/scheduleRestrictionValidation'
import type { BlockedWindow, ScheduleRestriction } from 'products/alerts/frontend/types'

import { QuietHoursDayTimeline } from './QuietHoursDayTimeline'
import { normalizeTimeInput, useQuietHoursFieldsState } from './useQuietHoursFieldsState'

export interface QuietHoursFieldsProps {
    scheduleRestriction: ScheduleRestriction | null | undefined
    cadenceMinutes: number
    coarseIntervalLabel?: string
    teamTimezone: string
    onChange: (next: ScheduleRestriction | null) => void
}

export function QuietHoursFields({
    scheduleRestriction,
    cadenceMinutes,
    coarseIntervalLabel,
    teamTimezone,
    onChange,
}: QuietHoursFieldsProps): JSX.Element {
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
        <div className="space-y-3">
            <LemonCheckbox
                checked={enabled}
                onChange={toggleEnabled}
                fullWidth
                label="Quiet hours"
                info="Alerts won't run during these hours in your project timezone. A check that would land in quiet hours is deferred to the next allowed time."
                data-attr="alertForm-quiet-hours-enabled"
            />
            {enabled ? (
                <>
                    {coarseIntervalLabel ? (
                        <LemonBanner type="info">
                            If a scheduled run would fall during quiet hours, it runs at the next allowed time in that
                            same day or cycle instead of waiting until the next {coarseIntervalLabel}.
                        </LemonBanner>
                    ) : null}
                    <div className="flex flex-wrap gap-2">
                        <LemonButton type="secondary" size="small" onClick={applyOvernightPreset}>
                            Preset: overnight (10 PM to 7 AM)
                        </LemonButton>
                    </div>
                    {highFrequencySlotPreview ? (
                        <div className="text-muted text-sm">
                            For {highFrequencySlotPreview.cadenceLabel} alerts we schedule about one check every{' '}
                            {highFrequencySlotPreview.intervalLabel}. Roughly {highFrequencySlotPreview.slotApprox} of
                            the next {highFrequencySlotPreview.totalSlots} slots would still run outside quiet hours.
                        </div>
                    ) : null}
                    {quietIssue ? <LemonBanner type="error">{quietIssue.message}</LemonBanner> : null}
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                        {windows.map((row: BlockedWindow, index: number) => (
                            // Index-only key: times change while typing; including start/end remounts inputs and drops focus.
                            <div key={index} className="min-w-0">
                                <div className="flex flex-wrap items-center gap-2">
                                    <LemonInput
                                        type="time"
                                        step={60}
                                        value={row.start}
                                        status={
                                            quietIssue?.kind === 'row' && quietIssue.index === index
                                                ? 'danger'
                                                : 'default'
                                        }
                                        onChange={(v: string) => updateRow(index, 'start', v)}
                                        onBlur={(e: FocusEvent<HTMLInputElement>) =>
                                            updateRow(index, 'start', normalizeTimeInput(e.currentTarget.value))
                                        }
                                        aria-label={`Quiet hours period ${index + 1} start time`}
                                        data-attr={`alertForm-quiet-start-${index}`}
                                    />
                                    <span className="text-muted">to</span>
                                    <LemonInput
                                        type="time"
                                        step={60}
                                        value={row.end}
                                        status={
                                            quietIssue?.kind === 'row' && quietIssue.index === index
                                                ? 'danger'
                                                : 'default'
                                        }
                                        onChange={(v: string) => updateRow(index, 'end', v)}
                                        onBlur={(e: FocusEvent<HTMLInputElement>) =>
                                            updateRow(index, 'end', normalizeTimeInput(e.currentTarget.value))
                                        }
                                        aria-label={`Quiet hours period ${index + 1} end time`}
                                        data-attr={`alertForm-quiet-end-${index}`}
                                    />
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        icon={<IconTrash className="size-4 text-danger" />}
                                        onClick={() => removeRow(index)}
                                        aria-label={`Remove quiet hours period ${index + 1}`}
                                        data-attr={`alertForm-quiet-remove-${index}`}
                                    />
                                </div>
                            </div>
                        ))}
                    </div>
                    <div>
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={addRow}
                            disabledReason={
                                atWindowLimit
                                    ? `Each alert can use up to ${MAX_BLOCKED_WINDOWS} quiet hour periods. Remove one to add another.`
                                    : undefined
                            }
                            data-attr="alertForm-quiet-add-period"
                        >
                            {addWindowButtonLabel}
                        </LemonButton>
                    </div>
                    {!quietIssue && windows.length > 0 ? <QuietHoursDayTimeline windows={windows} /> : null}
                    <p className="text-muted text-sm m-0">
                        We will not evaluate this alert during these hours. If a scheduled run falls in a window, we run
                        it when the window ends.
                    </p>
                </>
            ) : null}
        </div>
    )
}
