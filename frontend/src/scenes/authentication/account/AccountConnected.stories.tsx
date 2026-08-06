import { Meta, StoryObj } from '@storybook/react'

import { urls } from 'scenes/urls'

import { useStorybookMocks } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import { AccountConnected } from './AccountConnected'

const meta: Meta<typeof AccountConnected> = {
    title: 'Scenes-Other/Account Connected',
    component: AccountConnected,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}
export default meta

type Story = StoryObj<typeof AccountConnected>

const cloudPreflight = {
    ...preflightJson,
    cloud: true,
    realm: 'cloud',
}

const pageUrlFor = (
    kind: 'github-login' | 'github-integration' | 'slack-integration' | 'invalid',
    search: string = ''
): string => {
    return `${urls.accountConnected(kind)}${search}`
}

export const GithubIntegrationConnected: Story = {
    parameters: {
        pageUrl: pageUrlFor('github-integration', '?provider=github&installation_id=12345&project_id=2'),
    },
    render: () => {
        useStorybookMocks({ get: { '/_preflight': cloudPreflight } })
        return <AccountConnected kind="github-integration" />
    },
}

export const GithubIntegrationFailed: Story = {
    parameters: {
        pageUrl: pageUrlFor(
            'github-integration',
            '?provider=github&error=installation_failed&error_message=Installation%20could%20not%20be%20completed'
        ),
    },
    render: () => {
        useStorybookMocks({ get: { '/_preflight': cloudPreflight } })
        return <AccountConnected kind="github-integration" />
    },
}

export const GithubLoginLinked: Story = {
    parameters: {
        pageUrl: pageUrlFor('github-login', '?provider=github'),
    },
    render: () => {
        useStorybookMocks({ get: { '/_preflight': cloudPreflight } })
        return <AccountConnected kind="github-login" />
    },
}

export const GithubLoginFailed: Story = {
    parameters: {
        pageUrl: pageUrlFor('github-login', '?provider=github&error=already_linked'),
    },
    render: () => {
        useStorybookMocks({ get: { '/_preflight': cloudPreflight } })
        return <AccountConnected kind="github-login" />
    },
}

export const InvalidLink: Story = {
    parameters: {
        pageUrl: pageUrlFor('invalid'),
    },
    render: () => {
        useStorybookMocks({ get: { '/_preflight': cloudPreflight } })
        return <AccountConnected kind="invalid" />
    },
}
