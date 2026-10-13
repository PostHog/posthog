import type { SignalViewApi } from 'products/today/frontend/generated/api.schemas'

import { scoutLabel, sourceStyle } from './todaySignalReports'

export function textOf(value: unknown): string | null {
    return typeof value === 'string' && value.trim() ? value.trim() : null
}

export function signalSourceLabel(signal: Pick<SignalViewApi, 'source_product' | 'extra'>): string {
    const label = sourceStyle(signal.source_product).label
    if (signal.source_product !== 'signals_scout') {
        return label
    }
    return scoutLabel(textOf(signal.extra.skill_name)) ?? label
}
