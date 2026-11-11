import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'

import { userLogic } from 'scenes/userLogic'

import { useStorybookMocks } from '~/mocks/browser'

import { WorkloadTrustPolicies } from './WorkloadTrustPolicies'

const meta: Meta = {
    title: 'Scenes-Other/Settings/Project/Trusted workloads',
    component: WorkloadTrustPolicies,
    parameters: {
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

type Story = StoryObj<{}>

const ISSUER = 'https://token.actions.githubusercontent.com'

const providers = {
    supported: [
        {
            key: 'github_actions',
            name: 'GitHub Actions',
            issuer: ISSUER,
            docs_url: 'https://posthog.com/docs/api/workload-identity/github-actions',
            subject_claim: {
                name: 'repository_id',
                label: 'Repository ID',
                help_text: "GitHub's number for the repository. PostHog looks it up from the repository name.",
                placeholder: '123456789',
            },
            subject_name_claim: {
                name: 'repository',
                label: 'Repository',
                help_text: 'The owner and name, as GitHub shows them.',
                placeholder: 'owner/repo',
            },
            condition_claims: [
                { name: 'ref', label: 'Branch or tag', help_text: 'The full ref.', placeholder: 'refs/heads/main' },
                { name: 'environment', label: 'Environment', help_text: '', placeholder: 'production' },
                { name: 'event_name', label: 'Event', help_text: '', placeholder: 'push' },
            ],
            condition_presets: [
                {
                    key: 'branch_push',
                    label: 'Pushes to a branch',
                    help_text:
                        "Runs for commits pushed to this branch. Pull request runs don't match, even ones that target the branch.",
                    conditions: { ref: 'refs/heads/{value}', event_name: 'push' },
                    takes_value: true,
                    placeholder: 'main',
                    default_value: 'main',
                },
                {
                    key: 'environment',
                    label: 'A deployment environment',
                    help_text: 'Jobs that deploy to this GitHub environment.',
                    conditions: { environment: '{value}' },
                    takes_value: true,
                    placeholder: 'production',
                    default_value: 'production',
                },
            ],
            required_presets: [],
            default_presets: ['branch_push'],
            can_resolve_subject: true,
            setup_snippet:
                'permissions:\n  id-token: write # lets hog get an OIDC token for PostHog\n  contents: read\n',
        },
        {
            key: 'gitlab',
            name: 'GitLab',
            issuer: 'https://gitlab.com',
            docs_url: 'https://posthog.com/docs/api/workload-identity/gitlab',
            subject_claim: {
                name: 'project_id',
                label: 'Project ID',
                help_text: "GitLab's number for the project. PostHog looks it up from the project path.",
                placeholder: '12345678',
            },
            subject_name_claim: {
                name: 'project_path',
                label: 'Project path',
                help_text: 'The full path, as GitLab shows it, with any subgroups.',
                placeholder: 'group/project',
            },
            condition_claims: [
                { name: 'ref', label: 'Branch or tag', help_text: 'The short name.', placeholder: 'main' },
                { name: 'ref_type', label: 'Ref type', help_text: 'branch or tag.', placeholder: 'branch' },
                { name: 'environment', label: 'Environment', help_text: '', placeholder: 'production' },
            ],
            condition_presets: [
                {
                    key: 'branch',
                    label: 'A protected branch',
                    help_text: 'Pipelines that run on this branch while it is protected.',
                    conditions: { ref: '{value}', ref_type: 'branch', ref_protected: 'true' },
                    takes_value: true,
                    placeholder: 'main',
                    default_value: 'main',
                },
            ],
            required_presets: [],
            default_presets: ['branch'],
            can_resolve_subject: true,
            setup_snippet: 'your-job:\n  id_tokens:\n    HOG_ID_TOKEN:\n      aud: https://us.posthog.com\n',
        },
        {
            key: 'depot_ci',
            name: 'Depot CI',
            issuer: 'https://identity.depot.dev',
            docs_url: 'https://posthog.com/docs/api/workload-identity/depot',
            subject_claim: {
                name: 'repository_id',
                label: 'Repository ID',
                help_text: "The forge's number for the repository. PostHog looks it up from the repository name.",
                placeholder: '123456789',
            },
            subject_name_claim: {
                name: 'repository',
                label: 'Repository',
                help_text: 'The owner and name, as the forge shows them.',
                placeholder: 'owner/repo',
            },
            condition_claims: [
                { name: 'org_id', label: 'Depot organization ID', help_text: '', placeholder: 'abcd1234efgh' },
                { name: 'forge', label: 'Forge', help_text: '', placeholder: 'github' },
                { name: 'ref', label: 'Branch or tag', help_text: '', placeholder: 'refs/heads/main' },
                { name: 'event_name', label: 'Event', help_text: '', placeholder: 'push' },
            ],
            required_condition_claims: ['org_id', 'forge'],
            account_condition_claims: ['repository_owner_id'],
            subject_lookup_conditions: { forge: 'github' },
            condition_presets: [
                {
                    key: 'organization',
                    label: 'Your Depot organization',
                    help_text: 'Every policy pins your Depot organization and GitHub as the forge.',
                    conditions: { org_id: '{value}', forge: 'github' },
                    takes_value: true,
                    placeholder: 'abcd1234efgh',
                    default_value: '',
                },
                {
                    key: 'branch_push',
                    label: 'Pushes to a branch',
                    help_text: 'Runs for commits pushed to this branch.',
                    conditions: { ref: 'refs/heads/{value}', event_name: 'push' },
                    takes_value: true,
                    placeholder: 'main',
                    default_value: 'main',
                },
            ],
            required_presets: ['organization'],
            default_presets: ['organization', 'branch_push'],
            can_resolve_subject: true,
            setup_snippet: 'permissions:\n  id-token: write\n  contents: read\n',
        },
    ],
    job_settings: {
        host: 'https://us.posthog.com',
        project_id: 997,
        host_in_posthog_json: true,
    },
    grantable_scopes: [
        'annotation:read',
        'annotation:write',
        'error_tracking:read',
        'error_tracking:write',
        'organization_member:read',
        'organization_member:write',
    ],
    risky_scopes: {
        'organization_member:write': 'Invites and removes organization members and changes their roles.',
    },
}

const claimLabels = {
    subject: 'Repository ID',
    subject_name: 'Repository',
    conditions: { ref: 'Branch or tag', environment: 'Environment', event_name: 'Event' },
}

const createdBy = { id: 1, uuid: 'test-user', first_name: 'Test', email: 'test@example.com', hedgehog_config: null }

function TrustedWorkloads(): JSX.Element {
    // The section asks for a recent login on mount, so the story user has a fresh session before it renders.
    useState(() => {
        userLogic.mount()
        userLogic.actions.loadUserSuccess({
            ...MOCK_DEFAULT_USER,
            sensitive_session_expires_at: '2099-01-01T00:00:00Z',
        })
    })
    useStorybookMocks({
        post: {
            '/api/projects/:team_id/workload_trust_policies/': {
                id: 'deploys-new',
                name: 'Deploys',
                issuer: ISSUER,
                provider: 'github_actions',
                subject_name: 'Acme/web',
                subject: '123456',
                conditions: { event_name: 'push', ref: 'refs/heads/main' },
                claim_labels: claimLabels,
                scopes: ['error_tracking:write'],
                enabled: true,
                created_by: createdBy,
                created_at: '2026-10-03T10:00:00Z',
                updated_at: '2026-10-03T10:00:00Z',
            },
        },
        get: {
            '/api/projects/:team_id/workload_trust_policies/providers/': providers,
            '/api/projects/:team_id/workload_trust_policy_requests/resolve_subject/': {
                subject: '123456',
                subject_name: 'Acme/web',
                found_via: 'your GitHub integration',
            },
            '/api/projects/:team_id/workload_trust_policies/': {
                count: 2,
                next: null,
                previous: null,
                results: [
                    {
                        id: 'deploys',
                        name: 'Production deploys',
                        issuer: ISSUER,
                        provider: 'github_actions',
                        subject_name: 'acme/web',
                        subject: '123456',
                        conditions: { environment: 'production', ref: 'refs/heads/main' },
                        claim_labels: claimLabels,
                        scopes: ['annotation:write', 'error_tracking:write'],
                        enabled: true,
                        created_by: createdBy,
                        created_at: '2026-10-01T10:00:00Z',
                        updated_at: '2026-10-01T10:00:00Z',
                    },
                    {
                        id: 'previews',
                        name: 'Preview builds',
                        issuer: ISSUER,
                        provider: 'github_actions',
                        subject_name: 'acme/web',
                        subject: '123456',
                        conditions: { environment: 'preview' },
                        claim_labels: claimLabels,
                        scopes: ['error_tracking:write'],
                        enabled: false,
                        created_by: createdBy,
                        created_at: '2026-10-02T10:00:00Z',
                        updated_at: '2026-10-02T10:00:00Z',
                    },
                ],
            },
        },
    })
    return <WorkloadTrustPolicies />
}

export const WithPolicies: Story = {
    render: () => <TrustedWorkloads />,
}

export const AddingAGitHubRepository: Story = {
    render: () => <TrustedWorkloads />,
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        // The button stays disabled until the providers and policies load.
        const addButton = await waitFor(() => {
            const button = canvas.getByText('Add trusted workload').closest('button')
            if (!button || button.getAttribute('aria-disabled') === 'true') {
                throw new Error('Waiting for the trusted workloads to load')
            }
            return button
        })
        await userEvent.click(addButton)
        const body = within(canvasElement.ownerDocument.body)
        await userEvent.type(await body.findByPlaceholderText('owner/repo'), 'acme/web')
        await userEvent.click(await body.findByText('Look up'))
        await body.findByText('Found through your GitHub integration.')
    },
}

export const AfterAddingShowsTheJobSnippet: Story = {
    render: () => <TrustedWorkloads />,
    play: async (context) => {
        await AddingAGitHubRepository.play?.(context)
        const body = within(context.canvasElement.ownerDocument.body)
        await userEvent.type(await body.findByPlaceholderText('Production deploys'), 'Deploys')
        await userEvent.click((await body.findAllByText('Write'))[1])
        const submit = (await body.findAllByText('Add trusted workload')).at(-1)
        if (submit) {
            await userEvent.click(submit)
        }
        await body.findByText('Set up the workload')
    },
}
