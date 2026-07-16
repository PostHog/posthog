import { ExternalDataSource, ExternalDataSourceSchema } from '~/types'

import { schemasToEnableFor } from './signalSourcesLogic'

function schema(name: string, should_sync: boolean = false): ExternalDataSourceSchema {
    return { id: name, name, should_sync } as ExternalDataSourceSchema
}

function source(...schemas: ExternalDataSourceSchema[]): ExternalDataSource {
    return { source_type: 'Github', schemas } as ExternalDataSource
}

describe('signalSourcesLogic', () => {
    describe('schemasToEnableFor', () => {
        it.each([
            ['legacy bare row', [schema('issues')], ['issues']],
            ['single repo-qualified row', [schema('posthog/posthog.issues')], ['posthog/posthog.issues']],
            [
                'every repo of a multi-repo source',
                [schema('posthog/posthog.issues'), schema('posthog/other.issues')],
                ['posthog/posthog.issues', 'posthog/other.issues'],
            ],
            [
                'legacy bare row alongside an added repo',
                [schema('issues'), schema('posthog/other.issues')],
                ['issues', 'posthog/other.issues'],
            ],
            ['repo name containing dots', [schema('posthog/some.repo.issues')], ['posthog/some.repo.issues']],
            ['not other endpoints', [schema('posthog/posthog.pull_requests'), schema('issues')], ['issues']],
            ['nothing when a bare name merely contains the table', [schema('closed_issues')], []],
        ])('matches %s', (_name, schemas, expected) => {
            expect(schemasToEnableFor(source(...schemas), 'issues').map((s) => s.name)).toEqual(expected)
        })

        it('skips rows that are already syncing', () => {
            const rows = [schema('posthog/posthog.issues', true), schema('posthog/other.issues', false)]

            expect(schemasToEnableFor(source(...rows), 'issues').map((s) => s.name)).toEqual(['posthog/other.issues'])
        })

        it('handles a source with no schemas', () => {
            expect(schemasToEnableFor({ source_type: 'Github' } as ExternalDataSource, 'issues')).toEqual([])
        })
    })
})
