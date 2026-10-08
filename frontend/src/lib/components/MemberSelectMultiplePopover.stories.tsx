import { MOCK_DEFAULT_ORGANIZATION_MEMBER } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'

import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'
import { OrganizationMemberType } from '~/types'

import { MemberSelectMultiplePopover } from './MemberSelectMultiplePopover'

const FIRST_NAMES = [
    'Alice',
    'Ben',
    'Chloe',
    'Dan',
    'Eve',
    'Finn',
    'Grace',
    'Hugo',
    'Iris',
    'Jack',
    'Kara',
    'Leo',
    'Mia',
    'Noah',
    'Olive',
    'Pete',
    'Quinn',
    'Ruby',
]

const OTHER_MEMBERS: OrganizationMemberType[] = FIRST_NAMES.map((first_name, index) => ({
    ...MOCK_DEFAULT_ORGANIZATION_MEMBER,
    id: `member-${index}`,
    user: {
        id: 1000 + index,
        uuid: `member-user-${index}`,
        distinct_id: `member-user-${index}`,
        first_name,
        email: `${first_name.toLowerCase()}@example.com`,
    },
}))

const SELECTED_IDS = OTHER_MEMBERS.filter((member) => ['Pete', 'Quinn'].includes(member.user.first_name)).map(
    (member) => member.user.id
)

function StatefulPopover({ initialValue }: { initialValue: number[] }): JSX.Element {
    const [value, setValue] = useState(initialValue)
    return (
        <div className="flex justify-end w-120">
            <MemberSelectMultiplePopover value={value} onChange={setValue} />
        </div>
    )
}

const meta: Meta<typeof StatefulPopover> = {
    title: 'Components/Member select multiple popover',
    component: StatefulPopover,
    decorators: [
        mswDecorator({
            get: {
                '/api/organizations/:organization_id/members/': toPaginatedResponse([
                    MOCK_DEFAULT_ORGANIZATION_MEMBER,
                    ...OTHER_MEMBERS,
                ]),
            },
        }),
    ],
    parameters: {
        testOptions: { waitForSelector: '[aria-label="Members"] [aria-checked]' },
    },
}
export default meta

type Story = StoryObj<typeof StatefulPopover>

export const NothingSelected: Story = {
    args: { initialValue: [] },
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByText('Created by'))
    },
}

export const SelectedMembersOnOpen: Story = {
    args: { initialValue: SELECTED_IDS },
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByText('Created by (2)'))
    },
}
