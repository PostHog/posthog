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
 *   ''                 → no match
 *   '*'                → match all
 *   '123,456'          → only teams 123 and 456
 *   '*:0.1'            → 10% of all traffic (random per call)
 *   '123,*:0.05'       → team 123 always + 5% of all other teams
 *   '123:0.5'          → half of team 123's calls, no other team
 *   '123:0.5,*:0.05'   → half of team 123's calls + 5% of all other teams
 *
 * A team's own fraction replaces the '*' fraction for that team, so '123:0,*' is every team except 123.
 *
 * A fraction is a number between 0 and 1, so '*:10' is an error rather than "always". Any entry that does not parse
 * throws, as does a team or '*' that appears twice. A typo would otherwise read as a different rollout from the one
 * the operator meant, without any sign that it did.
 */
export function buildIntegerMatcherWithPercentage(config: string | undefined): ValueMatcher<number> {
    if (!config || config.trim().length === 0) {
        return () => false
    }

    const teamFractions = new Map<number, number>()
    let defaultFraction: number | undefined

    for (const part of config.split(',').map((s) => s.trim())) {
        const separator = part.indexOf(':')
        const target = (separator === -1 ? part : part.slice(0, separator)).trim()
        const fraction = separator === -1 ? 1 : parseFraction(part.slice(separator + 1).trim(), part)

        if (target === '*') {
            if (defaultFraction !== undefined) {
                throw new Error(`'*' appears more than once in '${config}'`)
            }
            defaultFraction = fraction
        } else if (/^\d+$/.test(target)) {
            const teamId = Number(target)
            if (teamFractions.has(teamId)) {
                throw new Error(`team ${teamId} appears more than once in '${config}'`)
            }
            teamFractions.set(teamId, fraction)
        } else {
            throw new Error(`'${part}' in '${config}' is not a team id, '*', or either of them with ':<fraction>'`)
        }
    }

    return (teamId: number) => {
        const fraction = teamFractions.get(teamId) ?? defaultFraction ?? 0
        return fraction > 0 && Math.random() < fraction
    }
}

function parseFraction(value: string, part: string): number {
    // Number() rejects trailing junk that parseFloat would drop, so '0.5x' fails instead of reading as half.
    const fraction = Number(value)
    if (value === '' || !Number.isFinite(fraction) || fraction < 0 || fraction > 1) {
        throw new Error(`'${part}' takes a fraction between 0 and 1 after ':', got '${value}'`)
    }
    return fraction
}
