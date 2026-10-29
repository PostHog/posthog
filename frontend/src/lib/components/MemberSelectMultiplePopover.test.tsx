import { MOCK_DEFAULT_BASIC_USER, MOCK_SECOND_BASIC_USER, MOCK_USER_UUID } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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

    it.each([
        {
            picker: 'MemberSelectMultiplePopover',
            Picker: MemberSelectMultiplePopover,
            initialLabel: 'Created by (1)',
            reopenLabel: 'Created by (1)',
        },
        {
            picker: 'MemberMultiSelect',
            Picker: MemberMultiSelect,
            initialLabel: 'Rose',
            reopenLabel: 'Alice',
        },
    ])(
        '$picker moves selected members to the top only after reopening',
        async ({ Picker, initialLabel, reopenLabel }) => {
            renderPicker(Picker, [MOCK_SECOND_BASIC_USER.id])
            await userEvent.click(await screen.findByText(initialLabel))
            const members = await screen.findByLabelText('Members')
            await within(members).findByText('Alice')
            expectListedInOrder(members, 'Rose', 'John')

            await userEvent.click(within(members).getByText('Alice'))
            expectListedInOrder(members, 'John', 'Alice')
            await userEvent.click(within(members).getByText('Rose'))
            expectListedInOrder(members, 'Rose', 'John')
            expect(within(members).getByText('Rose').closest('[role="menuitemcheckbox"]')).toHaveAttribute(
                'aria-checked',
                'false'
            )

            await userEvent.type(screen.getByPlaceholderText('Search'), 'Ali')
            await userEvent.click(screen.getByText('Outside'))
            await waitFor(() => expect(screen.queryByLabelText('Members')).not.toBeInTheDocument())
            await userEvent.click(screen.getByText(reopenLabel))
            const reopenedMembers = await screen.findByLabelText('Members')
            expect(screen.getByPlaceholderText('Search')).toHaveValue('')
            expectListedInOrder(reopenedMembers, 'Alice', 'John')
            expectListedInOrder(reopenedMembers, 'John', 'Rose')
            expect(within(reopenedMembers).getByText('Alice').closest('[role="menuitemcheckbox"]')).toHaveAttribute(
                'aria-checked',
                'true'
            )
            expect(within(reopenedMembers).getAllByText('Alice')).toHaveLength(1)
        }
    )

    it('keeps three adjacent members in place while selecting them', async () => {
        renderPicker(MemberSelectMultiplePopover)
        await userEvent.click(screen.getByText('Created by'))
        const members = await screen.findByLabelText('Members')
        await within(members).findByText('Chloe')

        for (const name of ['Alice', 'Ben', 'Chloe']) {
            await userEvent.click(within(members).getByText(name))
            expect(screen.getAllByText(name)).toHaveLength(1)
        }
        expectListedInOrder(members, 'John', 'Alice')
        expectListedInOrder(members, 'Alice', 'Ben')
        expectListedInOrder(members, 'Ben', 'Chloe')
        for (const name of ['Alice', 'Ben', 'Chloe']) {
            expect(within(members).getByText(name).closest('[role="menuitemcheckbox"]')).toHaveAttribute(
                'aria-checked',
                'true'
            )
        }
    })

    it('shows a selected member only once during search', async () => {
        renderPicker(MemberSelectMultiplePopover, [MOCK_SECOND_BASIC_USER.id])
        await userEvent.click(screen.getByText('Created by (1)'))
        const members = await screen.findByLabelText('Members')
        await within(members).findByText('Rose')
        expectListedInOrder(members, 'Rose', 'John')

        fireEvent.change(screen.getByPlaceholderText('Search'), { target: { value: 'Rose' } })
        await within(members).findByText('Rose')
        expect(within(members).getByText('Rose').closest('[role="menuitemcheckbox"]')).toHaveAttribute(
            'aria-checked',
            'true'
        )
        expect(screen.getAllByText('Rose')).toHaveLength(1)
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
        '$picker clears the selection from the trigger and from the list',
        async ({ Picker, selectedLabel, emptyLabel }) => {
            renderPicker(Picker, [MOCK_SECOND_BASIC_USER.id])
            expect(await screen.findByText(selectedLabel)).toBeInTheDocument()

            await userEvent.click(screen.getByLabelText('Clear selection'))
            expect(screen.queryByLabelText('Clear selection')).not.toBeInTheDocument()
            expect(screen.queryByLabelText('Members')).not.toBeInTheDocument()
            expect(screen.getByText(emptyLabel).closest('button')).toHaveFocus()

            await userEvent.click(screen.getByText(emptyLabel))
            const members = await screen.findByLabelText('Members')
            await userEvent.click(await within(members).findByText('Rose'))
            await userEvent.click(document.querySelector<HTMLElement>('[data-attr="member-filter-clear-selection"]')!)
            expect(within(members).getByText('Rose').closest('[role="menuitemcheckbox"]')).toHaveAttribute(
                'aria-checked',
                'false'
            )
            expect(screen.getByPlaceholderText('Search')).toHaveFocus()
            // A closing Popover keeps the list mounted for its 50 ms exit, so wait past it before checking.
            await act(() => new Promise((resolve) => setTimeout(resolve, 100)))
            expect(screen.getByLabelText('Members')).toBeInTheDocument()
        }
    )
})
