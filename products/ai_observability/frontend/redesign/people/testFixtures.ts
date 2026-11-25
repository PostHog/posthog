import type { PersonListApi, PersonListItemApi } from '../../generated/api.schemas'

export const PEOPLE_URL = '/api/projects/:team_id/ai_observability/people/'
export const PEOPLE_NEW_COUNT_URL = '/api/projects/:team_id/ai_observability/people/new_count/'

export function makePersonListItem(overrides: Partial<PersonListItemApi> = {}): PersonListItemApi {
    const id = overrides.id ?? '0192f3c9-0000-7000-8000-000000000001'
    return {
        id,
        person: { distinctId: `user-${id.slice(-4)}`, label: `user-${id.slice(-4)}@example.com` },
        anonymous: false,
        sessionCount: 2,
        traceCount: 5,
        cost: 0.0425,
        firstSeenInRange: '2026-11-20T09:15:00Z',
        lastSeen: '2026-11-24T16:40:00Z',
        ...overrides,
    }
}

export const PERSON_URL = '/api/projects/:team_id/ai_observability/people/:person_id/'

export function makePersonListPage(ids: string[], overrides: Partial<PersonListApi> = {}): PersonListApi {
    const results = ids.map((id) => makePersonListItem({ id }))
    return {
        count: results.length,
        results,
        counts: { anonymous: 0 },
        lookbackDays: 30,
        needsIdentification: false,
        next: null,
        previous: null,
        ...overrides,
    }
}
