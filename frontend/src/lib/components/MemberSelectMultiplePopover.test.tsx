import { MOCK_DEFAULT_BASIC_USER, MOCK_SECOND_BASIC_USER, MOCK_USER_UUID } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'
import { useState } from 'react'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { OrganizationMemberType, UserBasicType } from '~/types'

import { MemberMultiSelect } from './MemberMultiSelect'
import { MemberSelectMultiplePopover } from './MemberSelectMultiplePopover'

function member(id: string, user: UserBasicType, level: number): OrganizationMemberType {
    return {
        id,
        user,
        level,
        joined_at: '2020-09-24T15:05:26Z',
        updated_at: '2020-09-24T15:05:26Z',
        is_2fa_enabled: false,
        has_social_auth: false,
        last_login: null,
    }
}

type PickerProps = { value: number[]; onChange: (value: number[]) => void }

function StatefulPicker({
    Picker,
    initialValue,
}: {
    Picker: (props: PickerProps) => JSX.Element
    initialValue: number[]
}): JSX.Element {
    const [value, setValue] = useState(initialValue)
    return <Picker value={value} onChange={setValue} />
}

describe('multi-select member pickers', () => {
    beforeEach(async () => {
        useMocks({
            get: {
                '/api/organizations/:organization_id/members/': {
                    results: [
                        member('1', MOCK_DEFAULT_BASIC_USER, 8),
                        member('2', MOCK_SECOND_BASIC_USER, 1),
                        ...['Alice', 'Ben', 'Chloe'].map((firstName, index) =>
                            member(
                                String(index + 3),
                                {
                                    ...MOCK_SECOND_BASIC_USER,
                                    id: index + 100,
                                    uuid: `member-${index}`,
                                    first_name: firstName,
                                    email: `${firstName.toLowerCase()}@example.com`,
                                },
                                1
                            )
                        ),
                    ],
                },
            },
        })
        initKeaTests()
        userLogic().mount()
        await expectLogic(userLogic).toMatchValues({ user: expect.objectContaining({ uuid: MOCK_USER_UUID }) })
    })

    afterEach(() => {
        cleanup()
    })

    function renderPicker(Picker: (props: PickerProps) => JSX.Element, initialValue: number[] = []): void {
        render(
            <Provider>
                <>
                    <StatefulPicker Picker={Picker} initialValue={initialValue} />
                    <button type="button">Outside</button>
                </>
            </Provider>
        )
    }

    function expectListedInOrder(list: HTMLElement, first: string, second: string): void {
        const firstRow = within(list).getByText(first)
        const secondRow = within(list).getByText(second)
        expect(firstRow.compareDocumentPosition(secondRow) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    }

    it('keeps the member list in place and updates selected duplicates after selection activity stops', async () => {
        renderPicker(MemberSelectMultiplePopover)
        await userEvent.click(screen.getByText('Created by'))
        const members = await screen.findByRole('list', { name: 'Members' })
        await within(members).findByText('Rose')
        expectListedInOrder(members, 'John', 'Rose')

        jest.useFakeTimers({ doNotFake: ['queueMicrotask', 'setImmediate'] })
        try {
            const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime })
            await user.click(within(members).getByText('Rose'))
            expect(screen.queryByRole('list', { name: 'Selected members' })).not.toBeInTheDocument()

            await act(async () => jest.advanceTimersByTime(400))
            await user.click(within(members).getByText('John'))
            await act(async () => jest.advanceTimersByTime(599))
            expect(screen.queryByRole('list', { name: 'Selected members' })).not.toBeInTheDocument()
            expectListedInOrder(members, 'John', 'Rose')

            await act(async () => jest.advanceTimersByTime(1))
            expect(screen.queryByRole('list', { name: 'Selected members' })).not.toBeInTheDocument()
            await user.unhover(members)
            await act(async () => jest.advanceTimersByTime(0))
            const selected = screen.getByRole('list', { name: 'Selected members' })
            expectListedInOrder(selected, 'John', 'Rose')
            expectListedInOrder(members, 'John', 'Rose')

            await user.click(within(selected).getByText('Rose'))
            expect(within(members).getByText('Rose').closest('[role="menuitemcheckbox"]')).toHaveAttribute(
                'aria-checked',
                'false'
            )
            await act(async () => jest.advanceTimersByTime(600))
            expect(within(screen.getByRole('list', { name: 'Selected members' })).getByText('Rose')).toBeInTheDocument()
            await user.unhover(selected)
            await act(async () => jest.advanceTimersByTime(0))
            expect(within(screen.getByRole('list', { name: 'Selected members' })).queryByText('Rose')).toBeNull()

            await user.click(within(members).getByText('John'))
            await user.unhover(members)
            await act(async () => jest.advanceTimersByTime(600))
            expect(screen.queryByRole('list', { name: 'Selected members' })).not.toBeInTheDocument()
            expectListedInOrder(members, 'John', 'Rose')
        } finally {
            jest.useRealTimers()
        }
    })

    it('keeps three adjacent members in place while the pointer stays on the list', async () => {
        renderPicker(MemberSelectMultiplePopover)
        await userEvent.click(screen.getByText('Created by'))
        const members = await screen.findByRole('list', { name: 'Members' })
        await within(members).findByText('Chloe')

        jest.useFakeTimers({ doNotFake: ['queueMicrotask', 'setImmediate'] })
        try {
            fireEvent.mouseEnter(members.parentElement!)
            for (const name of ['Alice', 'Ben', 'Chloe']) {
                fireEvent.click(within(members).getByText(name))
                await act(async () => jest.advanceTimersByTime(720))
                expect(screen.queryByRole('list', { name: 'Selected members' })).not.toBeInTheDocument()
            }
            expectListedInOrder(members, 'Alice', 'Ben')
            expectListedInOrder(members, 'Ben', 'Chloe')
            for (const name of ['Alice', 'Ben', 'Chloe']) {
                expect(within(members).getByText(name).closest('[role="menuitemcheckbox"]')).toHaveAttribute(
                    'aria-checked',
                    'true'
                )
            }

            fireEvent.mouseLeave(members.parentElement!)
            await act(async () => jest.advanceTimersByTime(0))
            const selected = screen.getByRole('list', { name: 'Selected members' })
            expect(within(selected).getAllByRole('menuitemcheckbox')).toHaveLength(3)
            expectListedInOrder(members, 'Alice', 'Ben')
            expectListedInOrder(members, 'Ben', 'Chloe')
        } finally {
            jest.useRealTimers()
        }
    })

    it('shows selected duplicates on open but hides them during search', async () => {
        renderPicker(MemberSelectMultiplePopover, [MOCK_SECOND_BASIC_USER.id])
        await userEvent.click(screen.getByText('Created by (1)'))
        const members = await screen.findByRole('list', { name: 'Members' })
        await within(members).findByText('Rose')
        expect(within(screen.getByRole('list', { name: 'Selected members' })).getByText('Rose')).toBeInTheDocument()
        expectListedInOrder(members, 'John', 'Rose')

        fireEvent.change(screen.getByPlaceholderText('Search'), { target: { value: 'Rose' } })
        expect(screen.queryByRole('list', { name: 'Selected members' })).not.toBeInTheDocument()
    })

    it.each([
        {
            picker: 'MemberSelectMultiplePopover',
            Picker: MemberSelectMultiplePopover,
            selectedLabel: 'Created by (1)',
            emptyLabel: 'Created by',
        },
        { picker: 'MemberMultiSelect', Picker: MemberMultiSelect, selectedLabel: 'Rose', emptyLabel: 'Any user' },
    ])(
        '$picker clears the selection from the trigger without opening the dropdown',
        async ({ Picker, selectedLabel, emptyLabel }) => {
            renderPicker(Picker, [MOCK_SECOND_BASIC_USER.id])
            expect(await screen.findByText(selectedLabel)).toBeInTheDocument()

            const clearButton = document.querySelector<HTMLElement>('[data-attr="member-filter-clear-x"]')
            expect(clearButton).not.toBeNull()
            await userEvent.click(clearButton!)

            expect(screen.getByText(emptyLabel)).toBeInTheDocument()
            expect(document.querySelector('[data-attr="member-filter-clear-x"]')).toBeNull()
            expect(screen.queryByLabelText('Members')).not.toBeInTheDocument()
        }
    )
})
