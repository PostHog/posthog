import { MOCK_DEFAULT_BASIC_USER, MOCK_SECOND_BASIC_USER, MOCK_USER_UUID } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { OrganizationMemberType, UserBasicType } from '~/types'

import { MemberSelect } from './MemberSelect'

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

describe('MemberSelect', () => {
    let onChange: jest.Mock

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
        onChange = jest.fn()
    })

    afterEach(() => {
        cleanup()
    })

    function renderSelect(props: Partial<Parameters<typeof MemberSelect>[0]> = {}): void {
        render(
            <Provider>
                <MemberSelect value={null} onChange={onChange} {...props} />
            </Provider>
        )
    }

    it('shows the current user at the top labelled "(you)"', async () => {
        renderSelect()
        await userEvent.click(screen.getByText('Any user'))

        await waitFor(() => {
            expect(screen.getByText(MOCK_DEFAULT_BASIC_USER.first_name)).toBeInTheDocument()
            expect(screen.getByText('(you)')).toBeInTheDocument()
        })
    })

    it('does not offer an excluded member', async () => {
        renderSelect({ excludedMembers: [MOCK_SECOND_BASIC_USER.id] })
        await userEvent.click(screen.getByText('Any user'))

        await waitFor(() => expect(screen.getByText(MOCK_DEFAULT_BASIC_USER.first_name)).toBeInTheDocument())
        expect(screen.queryByText(MOCK_SECOND_BASIC_USER.first_name)).not.toBeInTheDocument()
    })

    it('calls onChange with the picked user', async () => {
        renderSelect()
        await userEvent.click(screen.getByText('Any user'))

        await waitFor(() => expect(screen.getByText(MOCK_SECOND_BASIC_USER.first_name)).toBeInTheDocument())
        await userEvent.click(screen.getByText(MOCK_SECOND_BASIC_USER.first_name))

        expect(onChange).toHaveBeenCalledWith(MOCK_SECOND_BASIC_USER)
    })
})
