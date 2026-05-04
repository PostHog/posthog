import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { PropertyOperator } from '~/types'

import { DistinctIdSelect } from './DistinctIdSelect'

const MOCK_PERSONS = [
    {
        id: 1,
        uuid: 'person-uuid-1',
        distinct_ids: ['phil-distinct-id'],
        properties: { email: 'phil@posthog.com', name: 'Phil' },
        created_at: '2024-01-01',
        is_identified: true,
    },
    {
        id: 2,
        uuid: 'person-uuid-2',
        distinct_ids: ['sarah-distinct-id'],
        properties: { email: 'sarah@posthog.com', name: 'Sarah' },
        created_at: '2024-01-02',
        is_identified: true,
    },
    {
        id: 3,
        uuid: 'person-uuid-3',
        distinct_ids: ['anon-id-12345'],
        properties: {},
        created_at: '2024-01-03',
        is_identified: false,
    },
]

describe('DistinctIdSelect', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team/persons/': { results: MOCK_PERSONS, next: null },
            },
            post: {
                '/api/environments/:team/persons/batch_by_distinct_ids/': async (req: any) => {
                    const body = (await req.json()) as { distinct_ids?: string[] }
                    const distinctIds = body.distinct_ids ?? []
                    const results: Record<string, any> = {}
                    for (const person of MOCK_PERSONS) {
                        for (const did of person.distinct_ids) {
                            if (distinctIds.includes(did)) {
                                results[did] = person
                            }
                        }
                    }
                    return [200, { results }]
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('renders person display names in the dropdown, not raw distinct_ids', async () => {
        const onChange = jest.fn()
        render(
            <Provider>
                <DistinctIdSelect value={null} operator={PropertyOperator.Exact} onChange={onChange} />
            </Provider>
        )

        const input = screen.getByRole('textbox')
        await userEvent.click(input)

        await waitFor(() => {
            expect(screen.getByText('phil@posthog.com')).toBeInTheDocument()
            expect(screen.getByText('sarah@posthog.com')).toBeInTheDocument()
        })
    })

    it('stores the distinct_id as the value when selecting a person', async () => {
        const onChange = jest.fn()
        render(
            <Provider>
                <DistinctIdSelect value={null} operator={PropertyOperator.Exact} onChange={onChange} />
            </Provider>
        )

        const input = screen.getByRole('textbox')
        await userEvent.click(input)

        await waitFor(() => {
            expect(screen.getByText('phil@posthog.com')).toBeInTheDocument()
        })

        await userEvent.click(screen.getByText('phil@posthog.com'))

        expect(onChange).toHaveBeenCalledWith(['phil-distinct-id'])
    })

    it('resolves existing distinct_id values to display names', async () => {
        render(
            <Provider>
                <DistinctIdSelect value="sarah-distinct-id" operator={PropertyOperator.Exact} onChange={jest.fn()} />
            </Provider>
        )

        await waitFor(() => {
            expect(screen.getByText('sarah@posthog.com')).toBeInTheDocument()
        })
    })

    it('falls back to the raw distinct_id when the person has no display properties', async () => {
        render(
            <Provider>
                <DistinctIdSelect value={null} operator={PropertyOperator.Exact} onChange={jest.fn()} />
            </Provider>
        )

        const input = screen.getByRole('textbox')
        await userEvent.click(input)

        await waitFor(() => {
            expect(screen.getByText('anon-id-12345')).toBeInTheDocument()
        })
    })

    it('renders one option per distinct_id when a person owns multiple ids', async () => {
        useMocks({
            get: {
                '/api/environments/:team/persons/': {
                    results: [
                        {
                            id: 99,
                            uuid: 'person-uuid-multi',
                            distinct_ids: ['anon-uuid-aaa', 'multi@example.com', 'device-uuid-bbb'],
                            properties: { email: 'multi@example.com', name: 'Multi User' },
                            created_at: '2024-01-01',
                            is_identified: true,
                        },
                    ],
                    next: null,
                },
            },
        })

        render(
            <Provider>
                <DistinctIdSelect value={null} operator={PropertyOperator.Exact} onChange={jest.fn()} />
            </Provider>
        )

        const input = screen.getByRole('textbox')
        await userEvent.click(input)

        // All three distinct_ids should appear as separate options. The email also
        // appears as the muted secondary line on the two UUID options, so we expect
        // multiple occurrences of it but only one of each UUID.
        await waitFor(() => {
            expect(screen.getByText('anon-uuid-aaa')).toBeInTheDocument()
            expect(screen.getByText('device-uuid-bbb')).toBeInTheDocument()
            expect(screen.getAllByText('multi@example.com').length).toBeGreaterThanOrEqual(1)
        })
    })

    it('keeps state isolated when two pickers are mounted side by side', async () => {
        const onChangeA = jest.fn()
        const onChangeB = jest.fn()
        render(
            <Provider>
                <DistinctIdSelect value="phil-distinct-id" operator={PropertyOperator.Exact} onChange={onChangeA} />
                <DistinctIdSelect value="sarah-distinct-id" operator={PropertyOperator.Exact} onChange={onChangeB} />
            </Provider>
        )

        // Both initial values should resolve to their respective display names,
        // which only works if each instance has its own state.
        await waitFor(() => {
            expect(screen.getByText('phil@posthog.com')).toBeInTheDocument()
            expect(screen.getByText('sarah@posthog.com')).toBeInTheDocument()
        })
    })

    it('supports multi-select with exact operator', async () => {
        const onChange = jest.fn()
        render(
            <Provider>
                <DistinctIdSelect value={['phil-distinct-id']} operator={PropertyOperator.Exact} onChange={onChange} />
            </Provider>
        )

        const input = screen.getByRole('textbox')
        await userEvent.click(input)

        await waitFor(() => {
            expect(screen.getByText('sarah@posthog.com')).toBeInTheDocument()
        })

        await userEvent.click(screen.getByText('sarah@posthog.com'))

        expect(onChange).toHaveBeenCalledWith(['phil-distinct-id', 'sarah-distinct-id'])
    })
})
