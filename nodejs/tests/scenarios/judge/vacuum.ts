import { z } from 'zod'

import type { SettingType } from '../probe/vacuum-probe'
import type { MeasureEvidence, MeasurementDefinition } from './measurements'

type Measured = ReturnType<MeasurementDefinition['measure']>[number]

const unmeasured = (reason: string): Measured => ({ value: null, censored: true, unmeasured: reason })

const UNIT_SCALE: Record<string, number> = {
    B: 1,
    kB: 1024,
    MB: 1024 ** 2,
    GB: 1024 ** 3,
    TB: 1024 ** 4,
    us: 0.001,
    ms: 1,
    s: 1000,
    min: 60_000,
    h: 3_600_000,
    d: 86_400_000,
}

function settingValueOf(value: string, { unit, vartype }: SettingType): string {
    const text = value.trim()
    if (vartype === 'bool') {
        const lower = text.toLowerCase()
        return ['on', 'true', 'yes', '1'].includes(lower)
            ? 'on'
            : ['off', 'false', 'no', '0'].includes(lower)
              ? 'off'
              : text
    }
    const [, number, suffix] = /^(-?\d+(?:\.\d+)?)\s*([a-zA-Z]*)$/.exec(text) ?? []
    if (number === undefined || (vartype !== 'integer' && vartype !== 'real')) {
        return text
    }
    const scale = suffix ? UNIT_SCALE[suffix] : unit ? UNIT_SCALE[unit] : 1
    return scale === undefined ? text : String(Number(number) * scale)
}

function settingsDiffer({ vacuumSettings, autovacuumProfile }: MeasureEvidence): Measured[] {
    if (autovacuumProfile === undefined) {
        return [unmeasured('the profile names no autovacuum settings')]
    }
    if (vacuumSettings === undefined || 'error' in vacuumSettings) {
        return [unmeasured(`the autovacuum settings were not read${vacuumSettings ? `: ${vacuumSettings.error}` : ''}`)]
    }
    const { settings, types } = vacuumSettings
    const named = Object.keys(autovacuumProfile).sort()
    const unread = named.filter((name) => !(name in settings))
    const differ = named.filter(
        (name) =>
            name in settings &&
            settingValueOf(settings[name], types[name]) !== settingValueOf(autovacuumProfile[name], types[name])
    )
    return [
        { key: 'count', value: differ.length, ...(unread.length > 0 && { incomplete: true as const }) },
        ...differ.map((key) => ({ key, value: 1 })),
        ...unread.map((key) => ({ key, ...unmeasured(`PostgreSQL has no setting ${key}`) })),
    ]
}

export const SOAK_MEASUREMENTS: MeasurementDefinition[] = [
    { name: 'autovacuum_settings_differ', unit: 'settings', params: z.object({}).strict(), measure: settingsDiffer },
]
