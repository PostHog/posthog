import { z } from 'zod'

const UNIT_MS = { ms: 1, s: 1000, m: 60_000 } as const

export const Duration = z.string().regex(/^\d+(ms|s|m)$/, 'a duration such as 500ms, 30s or 5m')

export function durationMs(duration: string): number {
    const [, amount, unit] = /^(\d+)(ms|s|m)$/.exec(Duration.parse(duration))!
    return Number(amount) * UNIT_MS[unit as keyof typeof UNIT_MS]
}
