import '@testing-library/jest-dom'

import { cleanup, render, within } from '@testing-library/react'

import { FLAG_CALLS_COLUMNS, flagCallsListQuery } from 'scenes/feature-flags/flagCallsListQuery'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { groupLogic } from 'products/groups/frontend/logics/groupLogic'

import { FlagCallsList } from './FlagCallsList'

function flagCallRow(flag: string): any[] {
    return [
        {
            uuid: `uuid-${flag}`,
            event: '$feature_flag_called',
            distinct_id: 'user',
            timestamp: '2023-07-03T22:41:12Z',
            properties: { $feature_flag: flag },
            elements_chain: '',
        },
        flag,
        true,
        { display_name: 'user@example.com', id: 'person', distinct_id: 'user' },
        null,
        'web',
        '2023-07-03T22:41:12Z',
    ]
}

function groupQuery(groupKey: string): ReturnType<typeof flagCallsListQuery> {
    return flagCallsListQuery({
        select: FLAG_CALLS_COLUMNS,
        fixedProperties: [
            { key: '$group_0', value: groupKey, type: PropertyFilterType.Event, operator: PropertyOperator.Exact },
        ],
    })
}

describe('FlagCallsList', () => {
    beforeEach(() => {
        useMocks({
            get: { '/api/environments/:team_id/groups/find/': { status: 404 } },
            post: {
                '/api/environments/:team_id/query/:kind/': async ({ request }) => {
                    const query = ((await request.json()) as any).query
                    if (query.kind !== 'EventsQuery') {
                        return [200, { results: [] }]
                    }
                    const groupKey = query.fixedProperties[0].value
                    return [
                        200,
                        { columns: FLAG_CALLS_COLUMNS, hasMore: false, results: [flagCallRow(`flag-of-${groupKey}`)] },
                    ]
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('shows each mounted list its own calls', async () => {
        const groupKeys = ['acme', 'globex']
        const lists = groupKeys.map((groupKey) => {
            const logic = groupLogic({ groupTypeIndex: 0, groupKey })
            logic.mount()
            const { container } = render(
                <FlagCallsList
                    uniqueKey="group-flag-calls"
                    attachTo={logic}
                    query={groupQuery(groupKey)}
                    setQuery={() => {}}
                    reachesPastRetention={false}
                />
            )
            return { groupKey, container }
        })

        for (const { groupKey, container } of lists) {
            const list = within(container)
            expect(await list.findByText(`flag-of-${groupKey}`)).toBeInTheDocument()
            for (const otherKey of groupKeys.filter((key) => key !== groupKey)) {
                expect(list.queryByText(`flag-of-${otherKey}`)).not.toBeInTheDocument()
            }
        }
    })
})
