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
            return Math.random() < percentage
        }
        return false
    }
}
