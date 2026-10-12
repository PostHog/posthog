import { DateTime } from 'luxon'

import { registerAsyncFunction } from '../async-function-registry'
import {
    FeatureFlagListQuery,
    FeatureFlagListResult,
    FeatureFlagStatusFilter,
    FeatureFlagTargetingMatch,
} from '../services/feature-flags/feature-flag-repository'

const DEFAULT_LIMIT = 25
const MAX_LIMIT = 100
// All workflow variables together must stay under 5KB, or the step fails. This leaves room for other variables.
const MAX_RESULT_BYTES = 4096
const MAX_CREATED_BY_EMAILS = 100

function optionalString(value: unknown): string | null {
    if (value === null || value === undefined) {
        return null
    }
    const trimmed = String(value).trim()
    return trimmed === '' ? null : trimmed
}

function optionalNonNegativeNumber(value: unknown, name: string): number | null {
    const raw = optionalString(value)
    if (raw === null) {
        return null
    }
    const parsed = Number(raw)
    if (!Number.isFinite(parsed) || parsed < 0) {
        throw new Error(`[HogFunction] - postHogGetFeatureFlags '${name}' must be a number of 0 or more, got '${raw}'`)
    }
    return parsed
}

function optionalEmailList(value: unknown): string[] | null {
    const parts = Array.isArray(value) ? value : String(value ?? '').split(/[\s,;]+/)
    const emails = [...new Set(parts.map((part) => String(part).trim().toLowerCase()).filter((part) => part !== ''))]
    if (emails.length > MAX_CREATED_BY_EMAILS) {
        throw new Error(
            `[HogFunction] - postHogGetFeatureFlags 'created_by_emails' takes up to ${MAX_CREATED_BY_EMAILS} emails, got ${emails.length}`
        )
    }
    return emails.length > 0 ? emails : null
}

function daysAgo(days: number | null): Date | null {
    return days === null ? null : DateTime.utc().minus({ days }).toJSDate()
}

function parseFeatureFlagListQuery(opts: Record<string, unknown> | undefined): FeatureFlagListQuery {
    const status = optionalString(opts?.status) ?? 'enabled'
    if (!['any', 'enabled', 'disabled'].includes(status)) {
        throw new Error(`[HogFunction] - postHogGetFeatureFlags 'status' must be any, enabled or disabled`)
    }

    const property = optionalString(opts?.targeting_property)
    const value = optionalString(opts?.targeting_value)
    if ((property === null) !== (value === null)) {
        throw new Error(
            `[HogFunction] - postHogGetFeatureFlags needs both 'targeting_property' and 'targeting_value', or neither`
        )
    }
    const match = optionalString(opts?.targeting_match) ?? 'includes'
    if (!['only', 'includes'].includes(match)) {
        throw new Error(`[HogFunction] - postHogGetFeatureFlags 'targeting_match' must be only or includes`)
    }

    const limit = optionalNonNegativeNumber(opts?.limit, 'limit') ?? DEFAULT_LIMIT

    return {
        status: status as FeatureFlagStatusFilter,
        search: optionalString(opts?.search),
        createdBefore: daysAgo(
            optionalNonNegativeNumber(opts?.created_more_than_days_ago, 'created_more_than_days_ago')
        ),
        updatedBefore: daysAgo(
            optionalNonNegativeNumber(opts?.updated_more_than_days_ago, 'updated_more_than_days_ago')
        ),
        targeting:
            property !== null && value !== null ? { property, value, match: match as FeatureFlagTargetingMatch } : null,
        createdByEmails: optionalEmailList(opts?.created_by_emails),
        limit: Math.min(Math.max(Math.floor(limit), 1), MAX_LIMIT),
    }
}

function fitToVariableSizeLimit(result: FeatureFlagListResult): FeatureFlagListResult {
    const flags = [...result.flags]
    const build = (): FeatureFlagListResult => ({
        count: flags.length,
        keys: flags.map((flag) => flag.key),
        flags,
        has_more: result.has_more || flags.length < result.flags.length,
    })
    let fitted = build()
    while (flags.length > 0 && Buffer.byteLength(JSON.stringify(fitted), 'utf8') > MAX_RESULT_BYTES) {
        flags.pop()
        fitted = build()
    }
    return fitted
}

registerAsyncFunction('postHogGetFeatureFlags', {
    execute: async (args, context, result) => {
        const [opts] = args as [Record<string, unknown> | undefined]
        const query = parseFeatureFlagListQuery(opts)

        context.consumeInlineAsyncBudget()

        // Flags belong to the project's root team, which can differ from the environment that runs the workflow.
        const team = await context.teamManager.getTeam(context.invocation.teamId)
        const rootTeamId = team?.project_id ?? context.invocation.teamId

        const flags = fitToVariableSizeLimit(await context.featureFlagRepository.list(rootTeamId, query))

        // Return value contract: see example.ts.
        result.invocation.state.vmState?.stack.push(flags)
    },

    mock: (args, logs): FeatureFlagListResult => {
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Async function 'postHogGetFeatureFlags' was mocked with arguments:`,
        })
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `postHogGetFeatureFlags(${JSON.stringify(args[0], null, 2)})`,
        })

        const now = DateTime.utc()
        return {
            count: 1,
            keys: ['mock-feature-flag'],
            flags: [
                {
                    id: 1,
                    key: 'mock-feature-flag',
                    name: 'Mock feature flag',
                    active: true,
                    created_at: now.minus({ days: 30 }).toISO()!,
                    updated_at: now.minus({ days: 10 }).toISO(),
                    created_by_email: 'owner@example.com',
                },
            ],
            has_more: false,
        }
    },
})
