import { useMemo } from 'react'

import { estimateCheckSlotsNext24h } from 'products/alerts/frontend/logic/scheduleRestrictionPreview'
import {
    findQuietHoursIssues,
    MAX_BLOCKED_WINDOWS,
    type QuietHoursIssue,
} from 'products/alerts/frontend/logic/scheduleRestrictionValidation'
import type { BlockedWindow, ScheduleRestriction } from 'products/alerts/frontend/types'

const DEFAULT_OVERNIGHT: BlockedWindow = { start: '22:00', end: '07:00' }

/** Canonical HH:MM for persisted values. Use on blur, not on every keystroke, because `type="time"` needs a valid value each render. */
export function normalizeTimeInput(v: string): string {
    const match = /^(\d{1,2}):(\d{1,2})$/.exec(v.trim())
    if (!match) {
        return v.trim()
    }
    const h = Math.min(23, Math.max(0, parseInt(match[1], 10)))
    const mn = Math.min(59, Math.max(0, parseInt(match[2], 10)))
    return `${String(h).padStart(2, '0')}:${String(mn).padStart(2, '0')}`
}

export interface QuietHoursFieldsStateInput {
    scheduleRestriction: ScheduleRestriction | null | undefined
    cadenceMinutes: number
    teamTimezone: string
    onChange: (next: ScheduleRestriction | null) => void
}

export interface QuietHoursFieldsState {
    enabled: boolean
    windows: BlockedWindow[]
    toggleEnabled: (checked: boolean) => void
    updateRow: (index: number, field: keyof BlockedWindow, value: string) => void
    removeRow: (index: number) => void
    addRow: () => void
    applyOvernightPreset: () => void
    highFrequencySlotPreview: {
        slotApprox: number
        totalSlots: number
        cadenceLabel: string
        intervalLabel: string
    } | null
    quietIssue: QuietHoursIssue | null
    atWindowLimit: boolean
    addWindowButtonLabel: string
}

export function useQuietHoursFieldsState({
    scheduleRestriction,
    cadenceMinutes,
    teamTimezone,
    onChange,
}: QuietHoursFieldsStateInput): QuietHoursFieldsState {
    const enabled = !!scheduleRestriction?.blocked_windows?.length
    const windows = useMemo(() => scheduleRestriction?.blocked_windows ?? [], [scheduleRestriction?.blocked_windows])

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

    const highFrequencySlotPreview = useMemo(() => {
        if (!enabled || cadenceMinutes > 60) {
            return null
        }
        const slotApprox = estimateCheckSlotsNext24h(scheduleRestriction?.blocked_windows, teamTimezone, cadenceMinutes)
        const totalSlots = (24 * 60) / cadenceMinutes
        if (slotApprox >= totalSlots) {
            return null
        }
        return {
            slotApprox,
            totalSlots,
            cadenceLabel: `${cadenceMinutes}-minute`,
            intervalLabel: `${cadenceMinutes} minutes`,
        }
    }, [cadenceMinutes, enabled, scheduleRestriction?.blocked_windows, teamTimezone])

    const quietIssue = useMemo(
        () => (enabled && windows.length > 0 ? findQuietHoursIssues(windows) : null),
        [enabled, windows]
    )

    const atWindowLimit = windows.length >= MAX_BLOCKED_WINDOWS
    const addWindowButtonLabel = atWindowLimit ? `Maximum of ${MAX_BLOCKED_WINDOWS} time windows` : 'Add time window'

    return {
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
    }
}
