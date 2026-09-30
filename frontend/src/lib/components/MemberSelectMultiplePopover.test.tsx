import { MOCK_DEFAULT_BASIC_USER, MOCK_SECOND_BASIC_USER, MOCK_USER_UUID } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'
import { useState } from 'react'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { OrganizationMemberType, UserBasicType } from '~/types'

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

function StatefulPopover({ initialValue }: { initialValue: number[] }): JSX.Element {
    const [value, setValue] = useState(initialValue)
    return <MemberSelectMultiplePopover value={value} onChange={setValue} />
}

describe('MemberSelectMultiplePopover', () => {
    beforeEach(async () => {
        useMocks({
            get: {
                '/api/organizations/:organization_id/members/': {
                    results: [member('1', MOCK_DEFAULT_BASIC_USER, 8), member('2', MOCK_SECOND_BASIC_USER, 1)],
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

    function renderPopover(initialValue: number[] = []): void {
        render(
            <Provider>
                <>
                    <StatefulPopover initialValue={initialValue} />
                    <button type="button">Outside</button>
                </>
            </Provider>
        )
    }

    async function expectListedInOrder(first: string, second: string): Promise<void> {
        const firstRow = await screen.findByText(first)
        const secondRow = await screen.findByText(second)
        expect(firstRow.compareDocumentPosition(secondRow) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    }

    it('lists members selected at open first and keeps rows in place while toggling', async () => {
        renderPopover()
        await userEvent.click(screen.getByText('Created by'))
        await expectListedInOrder('John', 'Rose')

        await userEvent.click(screen.getByText('Rose'))
        expect(screen.getByText('Created by (1)')).toBeInTheDocument()
        await expectListedInOrder('John', 'Rose')

        await userEvent.click(screen.getByText('Outside'))
        await waitFor(() => expect(screen.queryByLabelText('Members')).not.toBeInTheDocument())
        await userEvent.click(screen.getByText('Created by (1)'))
        await expectListedInOrder('Rose', 'John')
    })

    it('clears the selection from the trigger without opening the dropdown', async () => {
        renderPopover([MOCK_SECOND_BASIC_USER.id])

        const clearButton = document.querySelector<HTMLElement>('[data-attr="member-filter-clear-x"]')
        expect(clearButton).not.toBeNull()
        await userEvent.click(clearButton!)

        expect(screen.getByText('Created by')).toBeInTheDocument()
        expect(document.querySelector('[data-attr="member-filter-clear-x"]')).toBeNull()
        expect(screen.queryByLabelText('Members')).not.toBeInTheDocument()
    })
})
