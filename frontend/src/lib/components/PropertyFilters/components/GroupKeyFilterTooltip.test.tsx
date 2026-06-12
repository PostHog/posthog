import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { GroupTypeIndex } from '~/types'

import { GroupKeyFilterTooltip } from './GroupKeyFilterTooltip'

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
                '/api/environments/:team/groups/find': (req: any) => {
                    const groupKey = req.url.searchParams.get('group_key')
                    const group = MOCK_GROUPS.find((g) => g.group_key === groupKey)
                    return group ? [200, group] : [404, { detail: 'Not found' }]
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('renders the resolved group name and key when the lookup succeeds', async () => {
        render(
            <Provider>
                <GroupKeyFilterTooltip
                    groupTypeIndex={0 as GroupTypeIndex}
                    groupKeys={['uuid-001']}
                    fallbackLabel="$group_key = uuid-001"
                />
            </Provider>
        )

        await waitFor(() => {
            expect(screen.getByText('Fjellride AB')).toBeInTheDocument()
        })
        expect(screen.getByText('uuid-001')).toBeInTheDocument()
        expect(screen.queryByText('$group_key = uuid-001')).not.toBeInTheDocument()
    })

    it('falls back to the raw group key as the name when the group has no name property', async () => {
        render(
            <Provider>
                <GroupKeyFilterTooltip
                    groupTypeIndex={0 as GroupTypeIndex}
                    groupKeys={['key-no-name']}
                    fallbackLabel="$group_key = key-no-name"
                />
            </Provider>
        )

        await waitFor(() => {
            expect(screen.getAllByText('key-no-name').length).toBeGreaterThan(0)
        })
    })

    it('caches a resolved lookup so the key is only fetched once across remounts', async () => {
        let findCalls = 0
        useMocks({
            get: {
                '/api/environments/:team/groups/find': (req: any) => {
                    findCalls++
                    const groupKey = req.url.searchParams.get('group_key')
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
                        groupKeys={['uuid-cache']}
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

    it('shows the fallback label when the group cannot be looked up', async () => {
        render(
            <Provider>
                <GroupKeyFilterTooltip
                    groupTypeIndex={0 as GroupTypeIndex}
                    groupKeys={['unknown-uuid']}
                    fallbackLabel="$group_key = unknown-uuid"
                />
            </Provider>
        )

        await waitFor(() => {
            expect(screen.getByText('$group_key = unknown-uuid')).toBeInTheDocument()
        })
    })
})
