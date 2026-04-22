import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { PropertyOperator } from '~/types'

import { GroupKeySelect } from './GroupKeySelect'

const MOCK_GROUPS = [
    {
        group_type_index: 0,
        group_key: 'uuid-001',
        group_properties: { name: 'Fjellride AB' },
        created_at: '2024-01-01',
    },
    {
        group_type_index: 0,
        group_key: 'uuid-002',
        group_properties: { name: 'Bitfusion PR LLC' },
        created_at: '2024-01-02',
    },
    {
        group_type_index: 0,
        group_key: 'uuid-003',
        group_properties: { name: 'NexusHub' },
        created_at: '2024-01-03',
    },
]

describe('GroupKeySelect', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team/groups/': {
                    results: MOCK_GROUPS,
                    next: null,
                },
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

    it('renders group names in the dropdown, not UUIDs', async () => {
        const onChange = jest.fn()
        render(
            <Provider>
                <GroupKeySelect value={null} groupTypeIndex={0} operator={PropertyOperator.Exact} onChange={onChange} />
            </Provider>
        )

        const input = screen.getByRole('textbox')
        await userEvent.click(input)

        await waitFor(() => {
            expect(screen.getByText('Fjellride AB')).toBeInTheDocument()
            expect(screen.getByText('Bitfusion PR LLC')).toBeInTheDocument()
            expect(screen.getByText('NexusHub')).toBeInTheDocument()
        })

        // UUIDs should not be visible as labels
        expect(screen.queryByText('uuid-001')).not.toBeInTheDocument()
    })

    it('stores group_key (UUID) as the value when selecting a group', async () => {
        const onChange = jest.fn()
        render(
            <Provider>
                <GroupKeySelect value={null} groupTypeIndex={0} operator={PropertyOperator.Exact} onChange={onChange} />
            </Provider>
        )

        const input = screen.getByRole('textbox')
        await userEvent.click(input)

        await waitFor(() => {
            expect(screen.getByText('Fjellride AB')).toBeInTheDocument()
        })

        await userEvent.click(screen.getByText('Fjellride AB'))

        expect(onChange).toHaveBeenCalledWith(['uuid-001'])
    })

    it('resolves existing UUID values to display names', async () => {
        const onChange = jest.fn()
        render(
            <Provider>
                <GroupKeySelect
                    value="uuid-002"
                    groupTypeIndex={0}
                    operator={PropertyOperator.Exact}
                    onChange={onChange}
                />
            </Provider>
        )

        // The component should resolve uuid-002 to "Bitfusion PR LLC"
        await waitFor(() => {
            expect(screen.getByText('Bitfusion PR LLC')).toBeInTheDocument()
        })
    })

    it('supports multi-select with exact operator', async () => {
        const onChange = jest.fn()
        render(
            <Provider>
                <GroupKeySelect
                    value={['uuid-001']}
                    groupTypeIndex={0}
                    operator={PropertyOperator.Exact}
                    onChange={onChange}
                />
            </Provider>
        )

        const input = screen.getByRole('textbox')
        await userEvent.click(input)

        await waitFor(() => {
            expect(screen.getByText('Bitfusion PR LLC')).toBeInTheDocument()
        })

        await userEvent.click(screen.getByText('Bitfusion PR LLC'))

        // Should be called with both values
        expect(onChange).toHaveBeenCalledWith(['uuid-001', 'uuid-002'])
    })

    it('falls back to group_key when group has no name property', async () => {
        useMocks({
            get: {
                '/api/environments/:team/groups/': {
                    results: [
                        {
                            group_type_index: 0,
                            group_key: 'key-no-name',
                            group_properties: {},
                            created_at: '2024-01-01',
                        },
                    ],
                    next: null,
                },
            },
        })

        render(
            <Provider>
                <GroupKeySelect
                    value={null}
                    groupTypeIndex={0}
                    operator={PropertyOperator.Exact}
                    onChange={jest.fn()}
                />
            </Provider>
        )

        const input = screen.getByRole('textbox')
        await userEvent.click(input)

        await waitFor(() => {
            expect(screen.getByText('key-no-name')).toBeInTheDocument()
        })
    })
})
