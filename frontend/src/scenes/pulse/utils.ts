import { percentage } from 'lib/utils'

import { PulseSensitivity } from './pulseTypes'

export function formatSignedPct(pct: number): string {
    return `${pct >= 0 ? '+' : ''}${percentage(pct, 0)}`
}

export type ChangeDirection = 'up' | 'down' | 'flat'

export interface ChangeDescriptor {
    direction: ChangeDirection
    tone: 'success' | 'danger' | 'muted'
    label: string
}

export function describeChange(pct: number): ChangeDescriptor {
    if (pct === 0) {
        return { direction: 'flat', tone: 'muted', label: 'flat' }
    }
    if (pct > 0) {
        return { direction: 'up', tone: 'success', label: formatSignedPct(pct) }
    }
    return { direction: 'down', tone: 'danger', label: formatSignedPct(pct) }
}

export const ROBUST_Z_TOOLTIP =
    'Robust z-score: how far this week sits from the typical week, measured against normal week-to-week noise. ' +
    'Higher means more unusual. Informational only — the change threshold decides what gets flagged.'

// Frontend mirror of the backend SENSITIVITY_PRESETS. Selecting a preset applies these thresholds locally.
export const SENSITIVITY_PRESETS: Record<
    Exclude<PulseSensitivity, 'custom'>,
    { min_change_pct: number; robust_z_threshold: number }
> = {
    conservative: { min_change_pct: 0.4, robust_z_threshold: 3.5 },
    balanced: { min_change_pct: 0.25, robust_z_threshold: 3.5 },
    sensitive: { min_change_pct: 0.15, robust_z_threshold: 3.0 },
}
