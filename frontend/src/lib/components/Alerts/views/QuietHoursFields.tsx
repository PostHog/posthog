import { useMemo, type FocusEvent } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCheckbox, LemonInput } from '@posthog/lemon-ui'

import { AlertCalculationInterval } from '~/queries/schema/schema-general'

import { estimateHourlyCheckSlotsNext24h } from '../scheduleRestrictionPreview'
import { findQuietHoursIssues, MAX_BLOCKED_WINDOWS } from '../scheduleRestrictionValidation'
import type { BlockedWindow, ScheduleRestriction } from '../types'
import { QuietHoursDayTimeline } from './QuietHoursDayTimeline'

const DEFAULT_OVERNIGHT: BlockedWindow = { start: '22:00', end: '07:00' }

/** Canonical HH:MM for persisted values. Use on blur, not on every keystroke — `type="time"` needs a valid value each render. */
function normalizeTimeInput(v: string): string {
    const match = /^(\d{1,2}):(\d{1,2})$/.exec(v.trim())
    if (!match) {
        return v.trim()
    }
    const h = Math.min(23, Math.max(0, parseInt(match[1], 10)))
    const mn = Math.min(59, Math.max(0, parseInt(match[2], 10)))
    return `${String(h).padStart(2, '0')}:${String(mn).padStart(2, '0')}`
}

export interface QuietHoursFieldsProps {
    scheduleRestriction: ScheduleRestriction | null | undefined
    calculationInterval: AlertCalculationInterval
    teamTimezone: string
    onChange: (next: ScheduleRestriction | null) => void
}

export function QuietHoursFields({
    scheduleRestriction,
    calculationInterval,
    teamTimezone,
    onChange,
}: QuietHoursFieldsProps): JSX.Element {
    const enabled = !!scheduleRestriction?.blocked_windows?.length
    const windows = scheduleRestriction?.blocked_windows ?? []

    const setWindows = (nextWindows: BlockedWindow[]): void => {
        if (nextWindows.length === 0) {
            onChange(null)
            return
        }
        onChange({ blocked_windows: nextWindows })
    }

    const toggleEnabled = (checked: boolean): void => {
        if (!checked) {
            onChange(null)
            return
        }
        onChange({ blocked_windows: [{ ...DEFAULT_OVERNIGHT }] })
    }

    const updateRow = (index: number, field: keyof BlockedWindow, value: string): void => {
        const next = windows.map((w: BlockedWindow, i: number) => (i === index ? { ...w, [field]: value } : w))
        setWindows(next)
    }

    const removeRow = (index: number): void => {
        const next = windows.filter((_: BlockedWindow, i: number) => i !== index)
        setWindows(next)
    }

    const addRow = (): void => {
        if (windows.length >= MAX_BLOCKED_WINDOWS) {
            return
        }
        setWindows([...windows, { start: '12:00', end: '13:00' }])
    }

    const applyOvernightPreset = (): void => {
        setWindows([{ ...DEFAULT_OVERNIGHT }])
    }

    const hourlyApprox = enabled
        ? estimateHourlyCheckSlotsNext24h(scheduleRestriction?.blocked_windows, teamTimezone)
        : null

    const quietIssue = useMemo(
        () => (enabled && windows.length > 0 ? findQuietHoursIssues(windows) : null),
        [enabled, windows]
    )

    const nonHourlyInterval =
        calculationInterval !== AlertCalculationInterval.HOURLY
            ? calculationInterval === AlertCalculationInterval.DAILY
                ? 'day'
                : calculationInterval === AlertCalculationInterval.WEEKLY
                  ? 'week'
                  : 'month'
            : null

    const atWindowLimit = windows.length >= MAX_BLOCKED_WINDOWS
    const addWindowButtonLabel = atWindowLimit ? `Maximum of ${MAX_BLOCKED_WINDOWS} time windows` : 'Add time window'

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
                    {nonHourlyInterval ? (
                        <LemonBanner type="info">
                            If a scheduled run would fall during quiet hours, it runs at the next allowed time in that
                            same day or cycle instead of waiting until the next {nonHourlyInterval}.
                        </LemonBanner>
                    ) : null}
                    <div className="flex flex-wrap gap-2">
                        <LemonButton type="secondary" size="small" onClick={applyOvernightPreset}>
                            Preset: overnight (10pm–7am)
                        </LemonButton>
                    </div>
                    {calculationInterval === AlertCalculationInterval.HOURLY &&
                    hourlyApprox != null &&
                    hourlyApprox < 24 ? (
                        <div className="text-muted text-sm">
                            For hourly alerts we schedule about one check per clock hour. Roughly {hourlyApprox} of the
                            next 24 hours would still run outside quiet hours.
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
                                        data-attr={`alertForm-quiet-end-${index}`}
                                    />
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        icon={<IconTrash className="size-4 text-danger" />}
                                        onClick={() => removeRow(index)}
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
