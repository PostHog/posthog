import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { userLogic } from 'scenes/userLogic'

import { useStorybookMocks } from '~/mocks/browser'

import { OrgSwitcher } from './OrgSwitcher'

type StoryProps = { switchingToOrganizationId?: string }

const OTHER_ORGANIZATION = {
    id: '018f0000-0000-0000-0000-00000000abcd',
    name: 'Acme Corp',
    slug: 'acme-corp',
    membership_level: MOCK_DEFAULT_ORGANIZATION.membership_level,
    members_can_use_personal_api_keys: true,
    allow_publicly_shared_resources: true,
    is_active: true,
    is_not_active_reason: null,
    is_pending_deletion: false,
    logo_media_id: null,
}

const meta: Meta<(props: StoryProps) => JSX.Element> = {
    title: 'Components/Account/Org Switcher',
    parameters: {
        layout: 'centered',
        viewMode: 'story',
    },
    render: ({ switchingToOrganizationId }: StoryProps) => {
        useStorybookMocks({
            get: {
                '/api/users/@me/': () => [
                    200,
                    {
                        ...MOCK_DEFAULT_USER,
                        organizations: [
                            ...MOCK_DEFAULT_USER.organizations,
                            OTHER_ORGANIZATION,
                            { ...OTHER_ORGANIZATION, id: '018f0000-0000-0000-0000-00000000abce', name: 'Globex' },
                        ],
                    },
                ],
                '/api/organizations/@current/': () => [200, MOCK_DEFAULT_ORGANIZATION],
                '/api/environments/@current/': () => [200, MOCK_DEFAULT_TEAM],
                '/api/projects/@current/': () => [200, MOCK_DEFAULT_TEAM],
            },
            patch: {
                // Never answers, so the row stays in the state the user sees while a switch runs.
                '/api/users/@me/': () => new Promise<never>(() => {}),
            },
        })

        const { updateCurrentOrganization } = useActions(userLogic)
        useEffect(() => {
            if (switchingToOrganizationId) {
                updateCurrentOrganization(switchingToOrganizationId)
            }
        }, [switchingToOrganizationId, updateCurrentOrganization])

        return (
            <div className="w-[340px] border border-primary rounded bg-surface-primary">
                <OrgSwitcher dialog />
            </div>
        )
    },
}
export default meta

type Story = StoryObj<(props: StoryProps) => JSX.Element>

export const Default: Story = {}

export const SwitchingOrganization: Story = {
    args: { switchingToOrganizationId: OTHER_ORGANIZATION.id },
}
