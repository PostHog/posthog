import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'

export type FeatureFlagStatusFilter = 'any' | 'enabled' | 'disabled'

/**
 * `only`: every release condition that rolls out to anyone requires the property to equal the value.
 * `includes`: at least one release condition that rolls out to anyone requires it.
 */
export type FeatureFlagTargetingMatch = 'only' | 'includes'

export type FeatureFlagTargetingFilter = {
    property: string
    value: string
    match: FeatureFlagTargetingMatch
}

export type FeatureFlagListQuery = {
    status: FeatureFlagStatusFilter
    search: string | null
    createdBefore: Date | null
    updatedBefore: Date | null
    targeting: FeatureFlagTargetingFilter | null
    /** Lowercase emails. A flag matches when its creator has any of them. */
    createdByEmails: string[] | null
    limit: number
}

export type FeatureFlagSummary = {
    id: number
    key: string
    name: string
    active: boolean
    created_at: string
    updated_at: string | null
    created_by_email: string | null
}

export type FeatureFlagListResult = {
    count: number
    keys: string[]
    flags: FeatureFlagSummary[]
    /** More flags match than the result holds. */
    has_more: boolean
}

type FeatureFlagPropertyFilter = {
    key?: string
    value?: unknown
    operator?: string | null
}

type FeatureFlagConditionGroup = {
    properties?: FeatureFlagPropertyFilter[] | null
    rollout_percentage?: number | null
}

export type FeatureFlagFilters = {
    groups?: FeatureFlagConditionGroup[] | null
}

type FeatureFlagRow = {
    id: number
    key: string
    name: string | null
    filters: FeatureFlagFilters | null
    active: boolean
    // The Postgres type parser in common/utils/db/postgres.ts returns timestamps as ISO strings.
    created_at: string
    updated_at: string | null
    created_by_email: string | null
}

// The query keeps only flags with a condition on the property. The exact match runs in Node on at most this many rows.
const TARGETING_SCAN_LIMIT = 1000

function propertyValues(property: FeatureFlagPropertyFilter): string[] {
    const values = Array.isArray(property.value) ? property.value : [property.value]
    return values.filter((value) => value !== null && value !== undefined).map((value) => String(value).toLowerCase())
}

function isExactCondition(property: FeatureFlagPropertyFilter, key: string): boolean {
    return property.key === key && (property.operator ?? 'exact') === 'exact'
}

/**
 * Reads the flag's release conditions only. It does not evaluate the flag for a person, so cohort,
 * flag-dependency and non-exact operators never count as a match.
 */
export function flagMatchesTargeting(
    filters: FeatureFlagFilters | null,
    targeting: FeatureFlagTargetingFilter
): boolean {
    const value = targeting.value.toLowerCase()
    // A null rollout percentage means 100%.
    const releasingGroups = (filters?.groups ?? []).filter((group) => group.rollout_percentage !== 0)

    if (targeting.match === 'includes') {
        return releasingGroups.some((group) =>
            (group.properties ?? []).some(
                (property) => isExactCondition(property, targeting.property) && propertyValues(property).includes(value)
            )
        )
    }

    return (
        releasingGroups.length > 0 &&
        releasingGroups.every((group) =>
            (group.properties ?? []).some((property) => {
                const values = propertyValues(property)
                return (
                    isExactCondition(property, targeting.property) &&
                    values.length > 0 &&
                    values.every((v) => v === value)
                )
            })
        )
    )
}

function escapeLikePattern(value: string): string {
    return value.replace(/[\\%_]/g, (character) => `\\${character}`)
}

export class FeatureFlagRepository {
    constructor(private postgres: PostgresRouter) {}

    /** `teamId` must be the project's root team, because flags are stored on it. */
    public async list(teamId: number, query: FeatureFlagListQuery): Promise<FeatureFlagListResult> {
        const active = query.status === 'any' ? null : query.status === 'enabled'
        const search = query.search ? `%${escapeLikePattern(query.search)}%` : null
        // One extra row tells us whether more flags match than the limit allows.
        const scanLimit = query.targeting ? TARGETING_SCAN_LIMIT : query.limit + 1

        const { rows } = await this.postgres.query<FeatureFlagRow>(
            PostgresUse.COMMON_READ,
            `SELECT flag.id, flag.key, flag.name, flag.filters, flag.active, flag.created_at, flag.updated_at,
                    creator.email AS created_by_email
             FROM posthog_featureflag flag
             LEFT JOIN posthog_user creator ON creator.id = flag.created_by_id
             WHERE flag.team_id = $1
               AND flag.deleted = FALSE
               AND flag.archived = FALSE
               AND ($2::boolean IS NULL OR flag.active = $2)
               AND ($3::text IS NULL OR flag.key ILIKE $3 OR flag.name ILIKE $3)
               AND ($4::timestamptz IS NULL OR flag.created_at < $4)
               AND ($5::timestamptz IS NULL OR COALESCE(flag.updated_at, flag.created_at) < $5)
               AND ($7::text IS NULL OR jsonb_path_exists(
                   flag.filters,
                   '$.groups[*].properties[*] ? (@.key == $property)',
                   jsonb_build_object('property', $7::text)
               ))
               AND ($8::text[] IS NULL OR lower(creator.email) = ANY($8::text[]))
             ORDER BY flag.created_at DESC, flag.id DESC
             LIMIT $6`,
            [
                teamId,
                active,
                search,
                query.createdBefore,
                query.updatedBefore,
                scanLimit,
                query.targeting?.property ?? null,
                query.createdByEmails,
            ],
            'listFeatureFlagsForWorkflow'
        )

        const targeting = query.targeting
        const matching = targeting ? rows.filter((row) => flagMatchesTargeting(row.filters, targeting)) : rows
        const flags = matching.slice(0, query.limit).map(
            (row): FeatureFlagSummary => ({
                id: row.id,
                key: row.key,
                name: row.name ?? '',
                active: row.active,
                created_at: row.created_at,
                updated_at: row.updated_at,
                created_by_email: row.created_by_email,
            })
        )

        return {
            count: flags.length,
            keys: flags.map((flag) => flag.key),
            flags,
            has_more: matching.length > query.limit,
        }
    }
}
