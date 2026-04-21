import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import { ProjectSwitcher } from './ProjectSwitcher'

type StoryProps = { hasPendingInvite: boolean }

const PENDING_INVITE = {
    id: '018f0000-0000-0000-0000-000000000001',
    target_email: MOCK_DEFAULT_USER.email,
    organization_id: '018f0000-0000-0000-0000-00000000abcd',
    organization_name: 'Acme Corp',
    created_at: '2026-04-17T12:00:00Z',
}

const meta: Meta<(props: StoryProps) => JSX.Element> = {
    title: 'Components/Account/Project Switcher',
    parameters: {
        layout: 'centered',
        viewMode: 'story',
    },
    render: ({ hasPendingInvite }: StoryProps) => {
        useStorybookMocks({
            get: {
                '/api/users/@me/': () => [
                    200,
                    {
                        ...MOCK_DEFAULT_USER,
                        organization: MOCK_DEFAULT_ORGANIZATION,
                        pending_invites: hasPendingInvite ? [PENDING_INVITE] : [],
                    },
                ],
                '/api/environments/@current/': () => [200, MOCK_DEFAULT_TEAM],
                '/api/projects/@current/': () => [200, MOCK_DEFAULT_TEAM],
            },
        })

        return (
            <div className="w-[340px] border border-primary rounded bg-surface-primary">
                <ProjectSwitcher dialog />
            </div>
        )
    },
}
export default meta

type Story = StoryObj<(props: StoryProps) => JSX.Element>

export const NoPendingInvite: Story = {
    args: { hasPendingInvite: false },
}

export const WithPendingInvite: Story = {
    args: { hasPendingInvite: true },
}
