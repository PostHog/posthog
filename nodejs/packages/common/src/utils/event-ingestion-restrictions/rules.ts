// Restriction types that can be applied to events
export enum RestrictionType {
    DROP_EVENT = 1,
    SKIP_PERSON_PROCESSING = 2,
    FORCE_OVERFLOW = 3,
    REDIRECT_TO_DLQ = 4,
}

// Internal event context for matching against restrictions
// Field names match EventHeaders for direct pass-through
export interface EventContext {
    token?: string
    distinct_id?: string
    session_id?: string
    event?: string // event name
    uuid?: string // event uuid
}

// Filters for a restriction. AND logic between filter types, OR logic within each type.
// Empty set means "no filter on this field" (matches all).
export class RestrictionFilters {
    readonly distinctIds: ReadonlySet<string>
    readonly sessionIds: ReadonlySet<string>
    readonly eventNames: ReadonlySet<string>
    readonly eventUuids: ReadonlySet<string>

    constructor(config: {
        distinctIds?: string[]
        sessionIds?: string[]
        eventNames?: string[]
        eventUuids?: string[]
    }) {
        this.distinctIds = new Set(config.distinctIds ?? [])
        this.sessionIds = new Set(config.sessionIds ?? [])
        this.eventNames = new Set(config.eventNames ?? [])
        this.eventUuids = new Set(config.eventUuids ?? [])
    }

    // AND logic between filter types, OR within each type
    matches(event: EventContext): boolean {
        return (
            this.matchesField(this.distinctIds, event.distinct_id) &&
            this.matchesField(this.sessionIds, event.session_id) &&
            this.matchesField(this.eventNames, event.event) &&
            this.matchesField(this.eventUuids, event.uuid)
        )
    }

    private matchesField(filter: ReadonlySet<string>, value: string | undefined): boolean {
        if (filter.size === 0) {
            return true // Empty filter = matches all (neutral in AND)
        }
        return value !== undefined && filter.has(value)
    }

    isEmpty(): boolean {
        return (
            this.distinctIds.size === 0 &&
            this.sessionIds.size === 0 &&
            this.eventNames.size === 0 &&
            this.eventUuids.size === 0
        )
    }
}

// Scope of a restriction - either applies to all events or filtered events
export type RestrictionScope = { type: 'all' } | { type: 'filtered'; filters: RestrictionFilters }

// A single restriction rule combining type and scope
export interface RestrictionRule {
    restrictionType: RestrictionType
    scope: RestrictionScope
}

const EMPTY_RESTRICTIONS: ReadonlySet<RestrictionType> = new Set()

// Manages restrictions by token. Mirrors Rust RestrictionMap.
export class RestrictionMap {
    private restrictions: Map<string, RestrictionRule[]> = new Map()

    addRestriction(token: string, rule: RestrictionRule): void {
        const existing = this.restrictions.get(token) ?? []
        existing.push(rule)
        this.restrictions.set(token, existing)
    }

    getRestrictions(token: string, lookup?: EventContext): ReadonlySet<RestrictionType> {
        const tokenRestrictions = this.restrictions.get(token)
        if (!tokenRestrictions) {
            return EMPTY_RESTRICTIONS
        }

        const event: EventContext = {
            token,
            distinct_id: lookup?.distinct_id,
            session_id: lookup?.session_id,
            event: lookup?.event,
            uuid: lookup?.uuid,
        }

        const result = new Set<RestrictionType>()
        for (const rule of tokenRestrictions) {
            if (this.ruleMatches(rule, event)) {
                result.add(rule.restrictionType)
            }
        }
        return result
    }

    private ruleMatches(rule: RestrictionRule, event: EventContext): boolean {
        if (rule.scope.type === 'all') {
            return true
        }
        return rule.scope.filters.matches(event)
    }

    merge(other: RestrictionMap): void {
        for (const [token, rules] of other.restrictions) {
            for (const rule of rules) {
                this.addRestriction(token, rule)
            }
        }
    }
}
