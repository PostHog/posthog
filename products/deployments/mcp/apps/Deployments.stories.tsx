import type { Meta, StoryObj } from '@storybook/react'

import { McpThemeDecorator } from '@posthog/mcp-ui/storybook/decorator'

import { DeploymentListView, type DeploymentData, type DeploymentListData, DeploymentView } from './index'

const meta: Meta = {
    title: 'MCP Apps/Deployments',
    decorators: [McpThemeDecorator],
    parameters: {
        testOptions: {
            // McpThemeDecorator doesn't have dark mode built-in by default so just disable this to avoid duplicated snapshots
            skipDarkMode: true,
        },
    },
}
export default meta

type Story = StoryObj<{}>

const currentDeployment: DeploymentData = {
    id: 'd-7a3f9c2',
    status: 'ready',
    is_current: true,
    created_at: '2026-05-13T14:21:00Z',
    started_at: '2026-05-13T14:19:36Z',
    finished_at: '2026-05-13T14:21:00Z',
    duration_seconds: 84,
    commit_sha: '7a3f9c2',
    commit_message: 'feat: add deployments list page',
    commit_author_name: 'Alice Chen',
    commit_author_email: 'alice@acme.com',
    repo_url: 'https://github.com/acme/app',
    branch: 'main',
    deployment_url: 'https://acme-app.vercel.app',
    preview_image_url:
        'https://api.microlink.io/?url=https%3A%2F%2Facme-app.vercel.app&screenshot=true&meta=false&embed=screenshot.url',
    trigger_kind: 'git',
    triggered_by_deployment: null,
    _posthogUrl: 'https://us.posthog.com/project/1/deployments/d-7a3f9c2',
}

const failedDeployment: DeploymentData = {
    id: 'd-4be81da',
    status: 'error',
    is_current: false,
    created_at: '2026-05-13T12:08:00Z',
    started_at: '2026-05-13T12:07:18Z',
    finished_at: '2026-05-13T12:08:00Z',
    duration_seconds: 42,
    commit_sha: '4be81da',
    commit_message: 'fix: handle null author in commit metadata',
    commit_author_name: 'Bob Rivera',
    commit_author_email: 'bob@acme.com',
    repo_url: 'https://github.com/acme/app',
    branch: 'main',
    deployment_url: '',
    preview_image_url: '',
    trigger_kind: 'git',
    triggered_by_deployment: null,
}

const buildingDeployment: DeploymentData = {
    id: 'd-9f12cc3',
    status: 'building',
    is_current: false,
    created_at: '2026-05-13T11:55:00Z',
    started_at: '2026-05-13T11:54:21Z',
    finished_at: null,
    duration_seconds: null,
    commit_sha: '9f12cc3',
    commit_message: 'chore: bump posthog-js to 1.220.0',
    commit_author_name: 'Alice Chen',
    commit_author_email: 'alice@acme.com',
    repo_url: 'https://github.com/acme/app',
    branch: 'feat/upgrades',
    deployment_url: '',
    preview_image_url: '',
    trigger_kind: 'git',
    triggered_by_deployment: null,
}

const rolledBackDeployment: DeploymentData = {
    id: 'd-7e9d301',
    status: 'ready',
    is_current: false,
    created_at: '2026-05-09T20:30:00Z',
    started_at: '2026-05-09T20:28:36Z',
    finished_at: '2026-05-09T20:30:00Z',
    duration_seconds: 84,
    commit_sha: '7e9d301',
    commit_message: 'feat: rollback action wired up',
    commit_author_name: 'Cara Park',
    commit_author_email: 'cara@acme.com',
    repo_url: 'https://github.com/acme/app',
    branch: 'main',
    deployment_url: 'https://acme-app-7e9d301.vercel.app',
    preview_image_url: '',
    trigger_kind: 'rollback',
    triggered_by_deployment: 'd-4be81da',
}

export const Current: Story = {
    render: () => <DeploymentView deployment={currentDeployment} />,
    name: 'Ready (current) deployment',
}

export const BuildFailed: Story = {
    render: () => <DeploymentView deployment={failedDeployment} />,
    name: 'Build failed (no preview)',
}

export const Building: Story = {
    render: () => <DeploymentView deployment={buildingDeployment} />,
    name: 'Building deployment',
}

export const RolledBack: Story = {
    render: () => <DeploymentView deployment={rolledBackDeployment} />,
    name: 'Rollback-triggered deployment',
}

const sampleListData: DeploymentListData = {
    count: 4,
    results: [currentDeployment, failedDeployment, buildingDeployment, rolledBackDeployment],
    _posthogUrl: 'https://us.posthog.com/project/1/deployments',
}

export const List: Story = {
    render: () => <DeploymentListView data={sampleListData} />,
    name: 'Deployment list',
}

const emptyListData: DeploymentListData = {
    count: 0,
    results: [],
}

export const EmptyList: Story = {
    render: () => <DeploymentListView data={emptyListData} />,
    name: 'Empty list',
}
