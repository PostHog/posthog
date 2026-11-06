import type { Meta, StoryObj } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { useStorybookMocks } from '~/mocks/browser'
import type { Mocks } from '~/mocks/utils'

import type { FeatureRequestApi, FeatureRequestGitHubLinkApi } from '../../generated/api.schemas'
import { featureRequestGithubLogic } from './featureRequestGithubLogic'
import { FeatureRequestGithubSection } from './FeatureRequestGithubSection'
import { featureRequestsLogic } from './featureRequestsLogic'

const integration = {
    id: 12,
    kind: 'github' as const,
    display_name: 'Example GitHub',
    icon_url: '',
    config: {},
    created_at: '2024-01-01T00:00:00Z',
}

const linkedIssue: FeatureRequestGitHubLinkApi = {
    id: 'github-link-1',
    issue_url: 'https://github.com/posthog/example-repository/issues/123',
    repository: 'posthog/example-repository',
    issue_number: 123,
    issue_title: 'Show retention data in account reports',
    issue_state: 'open',
    sync_enabled: true,
    last_synced_at: '2024-01-14T10:00:00Z',
}

const unlinkedRequest: FeatureRequestApi = {
    id: 'feature-request-1',
    title: 'Show retention data in account reports',
    description: 'Example request used only for Storybook.',
    request_status: 'planned',
    request_priority: null,
    is_archived: false,
    archived_at: null,
    archived_by: null,
    version: 1,
    can_update: true,
    github_link: null,
    account: { id: 'account-1', name: 'Example account' },
    account_links: [],
    evidence_count: 0,
    product_areas: [],
    created_by: 1,
    updated_by: 1,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
}

const linkedRequest: FeatureRequestApi = { ...unlinkedRequest, github_link: linkedIssue }
const pausedRequest: FeatureRequestApi = {
    ...linkedRequest,
    github_link: { ...linkedIssue, sync_enabled: false },
}

interface SectionStoryProps {
    request: FeatureRequestApi
    integrations?: (typeof integration)[]
    post?: Mocks['post']
    mutationError?: string
    loading?: boolean
    width?: 'normal' | 'narrow'
}

function SectionStory({
    request,
    integrations = [integration],
    post = {},
    mutationError,
    loading = false,
    width = 'normal',
}: SectionStoryProps): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/feature_requests/': { count: 1, next: null, previous: null, results: [request] },
            '/api/projects/:team_id/feature_requests/:id/': request,
            '/api/projects/:team_id/feature_requests/:id/history/': [],
            '/api/projects/:team_id/feature_request_product_areas/': [],
            '/api/projects/:team_id/accounts/': { count: 0, next: null, previous: null, results: [] },
            '/api/projects/:team_id/integrations/': () => {
                if (loading) {
                    return new Promise<never>(() => {})
                }
                return {
                    count: integrations.length,
                    next: null,
                    previous: null,
                    results: integrations,
                }
            },
        },
        post,
    })

    const requestsLogic = featureRequestsLogic()
    const githubLogic = featureRequestGithubLogic({ requestId: request.id })
    const { activeRequest } = useValues(requestsLogic)
    const { loadActiveRequestSuccess } = useActions(requestsLogic)
    const { setMutationError } = useActions(githubLogic)

    useValues(integrationsLogic)

    useEffect(() => {
        loadActiveRequestSuccess(request)
        if (mutationError) {
            setMutationError(mutationError)
        }
    }, [loadActiveRequestSuccess, mutationError, request, setMutationError])

    return (
        <div className={width === 'narrow' ? 'w-[520px] p-4' : 'w-[900px] p-4'}>
            <FeatureRequestGithubSection request={activeRequest ?? request} />
        </div>
    )
}

const meta: Meta<typeof SectionStory> = {
    title: 'Customer analytics/Feature requests/GitHub issue',
    component: SectionStory,
    parameters: {
        layout: 'padded',
        featureFlags: [FEATURE_FLAGS.CUSTOMER_ANALYTICS],
    },
}
export default meta

type Story = StoryObj<typeof SectionStory>

export const Linked: Story = {
    args: {
        request: linkedRequest,
        post: {
            '/api/projects/:team_id/feature_requests/:id/pause_github/': pausedRequest,
            '/api/projects/:team_id/feature_requests/:id/unlink_github/': unlinkedRequest,
        },
    },
}

export const Paused: Story = {
    args: {
        request: pausedRequest,
        post: {
            '/api/projects/:team_id/feature_requests/:id/resume_github/': linkedRequest,
            '/api/projects/:team_id/feature_requests/:id/unlink_github/': unlinkedRequest,
        },
    },
}

export const Unlinked: Story = {
    args: {
        request: unlinkedRequest,
        post: {
            '/api/projects/:team_id/feature_requests/:id/link_github/': linkedRequest,
        },
    },
}

export const ReadOnly: Story = {
    args: {
        request: { ...linkedRequest, can_update: false },
    },
}

export const Archived: Story = {
    args: {
        request: { ...linkedRequest, is_archived: true },
    },
}

export const Error: Story = {
    args: {
        request: unlinkedRequest,
        mutationError: "Couldn't link this GitHub issue. Check the URL and try again.",
    },
}

export const Loading: Story = {
    args: {
        request: unlinkedRequest,
        loading: true,
    },
}

export const LinkedNarrow: Story = {
    args: {
        request: linkedRequest,
        width: 'narrow',
    },
}

export const UnlinkedNarrow: Story = {
    args: {
        request: unlinkedRequest,
        width: 'narrow',
    },
}
