import { principalLabel } from './principalLabel'

const CONTEXT = { teamNames: { 1: 'Hedgebox' }, currentUserId: 7 }

describe('principalLabel', () => {
    it.each([
        [
            'the server label wins',
            'posthog:materialization:team:1',
            'Materialized views · Project 2',
            'Materialized views · Project 2',
        ],
        ['a materialization login', 'posthog:materialization:team:1', undefined, 'Materialized views · Hedgebox'],
        ['a SQL editor login of someone else', 'posthog:sql-editor:team:1:user:9', undefined, 'SQL editor · Hedgebox'],
        [
            'your own SQL editor login in any project',
            'posthog:sql-editor:team:42:user:7',
            undefined,
            'SQL editor · You',
        ],
        [
            'a project missing from the organization list',
            'posthog:materialization:team:42',
            undefined,
            'Materialized views · Project 42',
        ],
        ['an unknown kind', 'posthog:data-imports:team:1', undefined, 'Data imports · Hedgebox'],
        ['a login that is not a PostHog principal', 'hl_metabase', undefined, 'hl_metabase'],
        ['an empty principal', '', undefined, 'Unknown'],
    ])('labels %s', (_name, principal, serverLabel, expected) => {
        expect(principalLabel(principal, CONTEXT, serverLabel)).toBe(expected)
    })
})
