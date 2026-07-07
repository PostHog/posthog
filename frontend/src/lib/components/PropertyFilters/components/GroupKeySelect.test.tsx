import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { PropertyOperator } from '~/types'

import { GroupKeySelect } from './GroupKeySelect'
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

// Resolvable via the find endpoint but absent from the list endpoint, like a
// pasted group key that the search results don't include.
const FIND_ONLY_GROUP = {
    group_type_index: 0,
    group_key: 'uuid-hidden',
    group_properties: { name: 'Hidden Co' },
    created_at: '2024-01-04',
}

describe('GroupKeySelect', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team/groups/': {
                    results: MOCK_GROUPS,
                    next: null,
                },
                '/api/environments/:team/groups/find': ({ request }) => {
                    const groupKey = new URL(request.url).searchParams.get('group_key')
                    const group = [...MOCK_GROUPS, FIND_ONLY_GROUP].find((g) => g.group_key === groupKey)
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

    it.each([
        {
            description: 'a group from the loaded options',
            value: 'uuid-001',
            snackLabel: 'Fjellride AB',
            expectedKeyInCard: 'uuid-001',
            forceSingleSelect: false,
        },
        {
            description: 'a pasted group key resolved lazily via the find endpoint',
            value: 'uuid-hidden',
            snackLabel: 'Hidden Co',
            expectedKeyInCard: 'uuid-hidden',
            forceSingleSelect: false,
        },
        {
            description: 'a single-select value snack',
            value: 'uuid-001',
            snackLabel: 'Fjellride AB',
            expectedKeyInCard: 'uuid-001',
            forceSingleSelect: true,
        },
    ])(
        'shows the group info card when hovering the selected value snack for $description',
        async ({ value, snackLabel, expectedKeyInCard, forceSingleSelect }) => {
            render(
                <Provider>
                    <GroupKeySelect
                        value={[value]}
                        groupTypeIndex={0}
                        operator={PropertyOperator.Exact}
                        onChange={jest.fn()}
                        forceSingleSelect={forceSingleSelect}
                    />
                </Provider>
            )

            const snack = await screen.findByText(snackLabel)
            await userEvent.hover(snack)

            // Wrap in a single waitFor so both assertions pass atomically — the
            // tooltip can briefly remount when the groups list finishes loading
            // (300ms debounce) and swaps GroupKeyFilterTooltip for GroupInfoCard.
            await waitFor(
                () => {
                    expect(screen.getByText(expectedKeyInCard)).toBeInTheDocument()
                    expect(screen.getByText(/First seen:/)).toBeInTheDocument()
                },
                { timeout: 3000 }
            )
        }
    )

    it('shows the group info card when hovering a dropdown option', async () => {
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

        const option = await screen.findByText('Bitfusion PR LLC')
        await userEvent.hover(option)

        await waitFor(
            () => {
                expect(screen.getByText('uuid-002')).toBeInTheDocument()
                expect(screen.getByText(/First seen:/)).toBeInTheDocument()
            },
            { timeout: 3000 }
        )
    })
})
