import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { GroupTypeIndex } from '~/types'

import { GroupKeyFilterTooltip } from './GroupKeyFilterTooltip'
import { clearGroupLookupCache } from './groupKeyTooltipLogic'

const MOCK_GROUPS = [
    {
        group_type_index: 0,
        group_key: 'uuid-001',
        group_properties: { name: 'Fjellride AB' },
        created_at: '2024-01-01',
    },
    {
        group_type_index: 0,
        group_key: 'key-no-name',
        group_properties: {},
        created_at: '2024-01-02',
    },
    {
        group_type_index: 0,
        group_key: 'uuid-cache',
        group_properties: { name: 'Cacheable Co' },
        created_at: '2024-01-03',
    },
]

describe('GroupKeyFilterTooltip', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team/groups/find': ({ request }) => {
                    const groupKey = new URL(request.url).searchParams.get('group_key')
                    const group = MOCK_GROUPS.find((g) => g.group_key === groupKey)
                    return group ? [200, group] : [404, { detail: 'Not found' }]
                },
            },
        })
        initKeaTests()
        clearGroupLookupCache()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        {
            description: 'the resolved group name when the lookup succeeds',
            groupKey: 'uuid-001',
            expectedText: 'Fjellride AB',
        },
        {
            description: 'the raw group key as the name when the group has no name property',
            groupKey: 'key-no-name',
            expectedText: 'key-no-name',
        },
        {
            description: 'the fallback label when the group cannot be looked up',
            groupKey: 'unknown-uuid',
            expectedText: '$group_key = unknown-uuid',
        },
    ])('renders $description', async ({ groupKey, expectedText }) => {
        render(
            <Provider>
                <GroupKeyFilterTooltip
                    groupTypeIndex={0 as GroupTypeIndex}
                    groupKey={groupKey}
                    fallbackLabel={`$group_key = ${groupKey}`}
                />
            </Provider>
        )

        await waitFor(() => {
            expect(screen.getAllByText(expectedText).length).toBeGreaterThan(0)
        })
    })

    it('caches a resolved lookup so the key is only fetched once across remounts', async () => {
        let findCalls = 0
        useMocks({
            get: {
                '/api/environments/:team/groups/find': ({ request }) => {
                    findCalls++
                    const groupKey = new URL(request.url).searchParams.get('group_key')
                    const group = MOCK_GROUPS.find((g) => g.group_key === groupKey)
                    return group ? [200, group] : [404, { detail: 'Not found' }]
                },
            },
        })

        const renderTooltip = (): ReturnType<typeof render> =>
            render(
                <Provider>
                    <GroupKeyFilterTooltip
                        groupTypeIndex={0 as GroupTypeIndex}
                        groupKey="uuid-cache"
                        fallbackLabel="$group_key = uuid-cache"
                    />
                </Provider>
            )

        const first = renderTooltip()
        await waitFor(() => {
            expect(screen.getByText('Cacheable Co')).toBeInTheDocument()
        })
        act(() => first.unmount())

        renderTooltip()
        await waitFor(() => {
            expect(screen.getByText('Cacheable Co')).toBeInTheDocument()
        })

        expect(findCalls).toBe(1)
    })
})
