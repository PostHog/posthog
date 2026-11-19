import { MOCK_DEFAULT_BASIC_USER, MOCK_SECOND_BASIC_USER } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { AssigneeDropdown } from '../Assignee/AssigneeDropdown'
import { assigneeSelectLogic } from '../Assignee/assigneeSelectLogic'
import { OutOfOfficeSwitch } from './OutOfOfficeSwitch'

const away = (user: typeof MOCK_DEFAULT_BASIC_USER): Record<string, unknown> => ({
    id: `ooo-${user.id}`,
    user,
    since: '2026-11-17T09:00:00Z',
})

const page = (results: Record<string, unknown>[]): Record<string, unknown> => ({
    count: results.length,
    next: null,
    previous: null,
    results,
})

function LoadedAssigneeDropdown(): JSX.Element {
    const { ensureAssigneeTypesLoaded } = useActions(assigneeSelectLogic)
    useEffect(() => ensureAssigneeTypesLoaded(), [ensureAssigneeTypesLoaded])
    return <AssigneeDropdown assignee={null} onChange={() => undefined} />
}

const meta: Meta = {
    title: 'Scenes-App/Support/Out of office',
    parameters: {
        layout: 'padded',
        mockDate: '2026-11-19',
        featureFlags: [FEATURE_FLAGS.PRODUCT_SUPPORT_OUT_OF_OFFICE],
    },
}
export default meta

type Story = StoryObj

export const SwitchOff: Story = {
    decorators: [mswDecorator({ get: { '/api/projects/:team_id/conversations/out_of_office/': page([]) } })],
    parameters: { testOptions: { waitForSelector: '[data-attr="support-out-of-office-switch"]' } },
    render: () => <OutOfOfficeSwitch />,
}

export const SwitchOn: Story = {
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team_id/conversations/out_of_office/': page([away(MOCK_DEFAULT_BASIC_USER)]) },
        }),
    ],
    parameters: { testOptions: { waitForSelector: '[data-attr="support-out-of-office-switch"]' } },
    render: () => <OutOfOfficeSwitch />,
}

export const AssigneeDropdownWithAwayTeammate: Story = {
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team_id/conversations/out_of_office/': page([away(MOCK_SECOND_BASIC_USER)]) },
        }),
    ],
    parameters: { testOptions: { waitForSelector: 'text=Away' } },
    render: () => (
        <div className="w-80">
            <LoadedAssigneeDropdown />
        </div>
    ),
}
