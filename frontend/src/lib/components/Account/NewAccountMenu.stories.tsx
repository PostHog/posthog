import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { OrganizationMembershipLevel } from 'lib/constants'

import { useStorybookMocks } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import { NewAccountMenu } from './NewAccountMenu'
import { newAccountMenuLogic } from './newAccountMenuLogic'

type StoryProps = { canCreateProjects: boolean }

const meta: Meta<(props: StoryProps) => JSX.Element> = {
    title: 'Components/Account/New Account Menu',
    parameters: {
        layout: 'centered',
        viewMode: 'story',
    },
    render: ({ canCreateProjects }: StoryProps) => {
        const organization = {
            ...MOCK_DEFAULT_ORGANIZATION,
            membership_level: canCreateProjects
                ? OrganizationMembershipLevel.Admin
                : OrganizationMembershipLevel.Member,
        }

        useStorybookMocks({
            get: {
                '/_preflight': { ...preflightJson, cloud: true, can_create_org: true },
                '/api/users/@me/': () => [200, { ...MOCK_DEFAULT_USER, organization, pending_invites: [] }],
                '/api/organizations/@current/': () => [200, organization],
                '/api/environments/@current/': () => [200, MOCK_DEFAULT_TEAM],
                '/api/projects/@current/': () => [200, MOCK_DEFAULT_TEAM],
            },
        })

        const { setAccountMenuOpen } = useActions(newAccountMenuLogic)
        useEffect(() => setAccountMenuOpen(true), [setAccountMenuOpen])

        return (
            <div className="w-56">
                <NewAccountMenu isLayoutNavCollapsed={false} />
            </div>
        )
    },
}
export default meta

type Story = StoryObj<(props: StoryProps) => JSX.Element>

export const CanCreateProjects: Story = {
    args: { canCreateProjects: true },
}

export const CannotCreateProjects: Story = {
    args: { canCreateProjects: false },
}
