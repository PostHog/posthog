import type { ValueMatcher } from '~/types'

// These live apart from config.ts because that module builds `defaultConfig` at import time and throws without
// database env. The session replay rasterizer reaches this code through its otel chain and has no such env.

export function buildIntegerMatcher(config: string | undefined, allowStar: boolean): ValueMatcher<number> {
    // Builds a ValueMatcher on a comma-separated list of values.
    // Optionally, supports a '*' value to match everything
    if (!config || config.trim().length == 0) {
        return () => false
    } else if (allowStar && config === '*') {
        return () => true
    } else {
        const values = new Set(
            config
                .split(',')
                .map((n) => parseInt(n))
                .filter((num) => !isNaN(num))
        )
        return (v: number) => {
            return values.has(v)
        }
    }
}

/**
 * Builds a matcher that supports team IDs and/or percentage-based rollout.
 *
 * Formats:
 *   ''          → no match
 *   '*'         → match all
 *   '123,456'   → only teams 123 and 456
 *   '*:0.1'     → 10% of all traffic (random per call)
 *   '123,*:0.05' → team 123 always + 5% of all other teams
 */
export function buildIntegerMatcherWithPercentage(config: string | undefined): ValueMatcher<number> {
    return buildRolloutMatcher(config, () => Math.random())
}

export function buildStableTeamMatcherWithPercentage(config: string | undefined): ValueMatcher<number> {
    return buildRolloutMatcher(config, (teamId) => (Math.imul(teamId, 0x9e3779b1) >>> 0) / 2 ** 32)
}

function buildRolloutMatcher(config: string | undefined, draw: (value: number) => number): ValueMatcher<number> {
    if (!config || config.trim().length === 0) {
        return () => false
    }
    if (config.trim() === '*') {
        return () => true
    }

    const parts = config.split(',').map((s) => s.trim())
    const teamIds = new Set<number>()
    let percentage = 0

    for (const part of parts) {
        if (part.startsWith('*:')) {
            percentage = parseFloat(part.slice(2))
        } else {
            const num = parseInt(part)
            if (!isNaN(num)) {
                teamIds.add(num)
            }
        }
    }

    return (teamId: number) => {
        if (teamIds.has(teamId)) {
            return true
        }
        if (percentage > 0) {
            return draw(teamId) < percentage
        }
        return false
    }
}

export function assertRolloutFractions(name: string, config: string): void {
    const fractions = config
        .split(',')
        .map((part) => part.trim())
        .filter((part) => part.startsWith('*:'))
        .map((part) => part.slice(2))
    for (const fraction of fractions) {
        const value = Number(fraction)
        if (fraction === '' || !Number.isFinite(value) || value < 0 || value > 1) {
            throw new Error(`${name} takes a fraction between 0 and 1 after '*:', got '${fraction}'`)
        }
    }
}
