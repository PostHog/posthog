import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'
import { installMockEventSource } from 'lib/wizard-sync/eventSource.mock'

import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { WizardRunApi } from 'products/wizard/frontend/generated/api.schemas'
import { wizardRunSyncLogic } from 'products/wizard/frontend/logics/wizardRunSyncLogic'

import { VERIFY_AI_EVENTS } from '../../hooks/useInstallationComplete'
import { VariantProps } from '../types'
import { WizardInstallStep } from './index'

// OnboardingStep pulls in half the app (support side panel, project tree). The stub keeps the
// contract that matters: the Continue button is driven by continueDisabledReason, which is
// computed by the real WizardInstallStep code under test.
jest.mock('../../../OnboardingStep', () => ({
    OnboardingStep: ({
        children,
        continueDisabledReason,
        actions,
        title,
    }: {
        children: React.ReactNode
        continueDisabledReason?: string
        actions?: React.ReactNode
        title: string
    }) => (
        <div>
            <h1>{title}</h1>
            {actions}
            {children}
            <button data-attr="mock-continue" aria-disabled={continueDisabledReason ? 'true' : undefined}>
                Continue
            </button>
        </div>
    ),
}))

// The realtime indicator is orthogonal here and drags in live-events deps.
jest.mock('../../RealtimeCheckIndicator', () => ({
    RealtimeCheckIndicator: () => <div data-attr="mock-realtime-check" />,
    AdblockWarning: () => null,
}))

// Manual-setup surfaces (behind a modal that stays closed) are not under test.
jest.mock('../SDKGrid', () => ({ SDKGrid: () => null }))
jest.mock('../SDKInstructionsModal', () => ({ SDKInstructionsModal: () => null }))

const AIO_PROPS: VariantProps = {
    sdkGridProps: {
        filteredSDKs: [],
        searchTerm: '',
        selectedTag: null,
        tags: [],
        onSDKClick: () => {},
        onSearchChange: () => {},
        onTagChange: () => {},
        currentTeam: null,
        installationComplete: false,
        showTopSkipButton: false,
    },
    sdkInstructionMap: {},
    adblockResult: 'ok' as VariantProps['adblockResult'],
    installationComplete: false,
    listeningForName: 'LLM generation',
    teamPropertyToVerify: VERIFY_AI_EVENTS,
    selectedSDK: null,
    installTitle: 'Install AI observability',
    wizardOverrides: {
        subcommand: 'ai-observability',
        description: 'Detects your LLM SDK and wires up tracing.',
        intro: 'The setup agent detects your LLM provider.',
        supports: [{ name: 'OpenAI' }, { name: 'Anthropic' }, { name: '+ 30 more' }],
    },
}

describe('WizardInstallStep with wizardOverrides', () => {
    let restoreEventSource: () => void
    beforeEach(() => {
        localStorage.clear()
        useMocks({
            get: {
                '/api/projects/:team_id/event_definitions': { results: [], count: 0 },
                '/api/projects/:team_id/wizard/runs/': { results: [], count: 0, next: null },
                '/api/projects/:team_id/wizard/runs/:run_id/tasks/': { tasks: [] },
                '/api/projects/:team_id/wizard/runs/:run_id/artifacts/': { results: [], count: 0 },
            },
            post: {
                '/api/environments/:team_id/query': { results: [] },
            },
        })
        initKeaTests()
        restoreEventSource = installMockEventSource()
    })

    afterEach(() => {
        cleanup()
        restoreEventSource()
        localStorage.clear()
    })

    it('shows the ai-observability command and blocks Continue until installation completes', async () => {
        const sync = wizardRunSyncLogic({ projectId: String(MOCK_DEFAULT_TEAM.id) })
        sync.mount()
        await expectLogic(sync).toFinishAllListeners()
        sync.actions.runsLoaded([
            {
                id: 'base-installation',
                team_id: MOCK_DEFAULT_TEAM.id,
                created_by_id: MOCK_DEFAULT_USER.id,
                program: { id: 'posthog-integration' },
                status: 'completed',
                created_at: new Date(Date.now() + 60_000).toISOString(),
            } as WizardRunApi,
        ])
        render(
            <Provider>
                <WizardInstallStep {...AIO_PROPS} />
            </Provider>
        )

        expect(await screen.findByText((t) => t.includes('ai-observability') && t.includes('npx'))).toBeInTheDocument()
        expect(document.querySelector('[data-attr="mock-continue"]')).toHaveAttribute('aria-disabled', 'true')
        expect(document.querySelector('[data-attr="wizard-install-sync"]')).toBeNull()
        sync.unmount()
    })

    it.each([false, true])(
        'allows continuing during setup and keeps result actions in onboarding (compact=%s)',
        async (compact) => {
            render(
                <Provider>
                    <WizardInstallStep
                        {...AIO_PROPS}
                        wizardOverrides={{ ...AIO_PROPS.wizardOverrides!, subcommand: '' }}
                        compact={compact}
                    />
                </Provider>
            )
            const sync = wizardRunSyncLogic({ projectId: String(MOCK_DEFAULT_TEAM.id) })
            await act(async () => {
                await expectLogic(sync).toFinishAllListeners()
            })
            const createdAt = new Date(Date.now() + 60_000).toISOString()
            const run: WizardRunApi = {
                id: 'installation',
                team_id: MOCK_DEFAULT_TEAM.id,
                created_by_id: MOCK_DEFAULT_USER.id,
                status: 'running',
                stage: 'executing_wizard',
                created_at: createdAt,
                updated_at: createdAt,
                environment: 'local',
                workspace: { type: 'local_folder', project_name: 'example-project' },
                program: {
                    id: 'posthog-integration',
                    name: 'PostHog integration',
                    description: '',
                    command: [],
                    wizard_version: '1.0.0',
                    tags: [],
                    required_programs: [],
                    supported_environments: ['local', 'cloud'],
                },
                created_by: null,
                error_code: null,
                error_message: null,
                started_at: null,
                finished_at: null,
                deadline_at: null,
            }
            await act(async () => {
                sync.actions.runsLoaded([run])
                await expectLogic(sync).toFinishAllListeners()
            })
            expect(document.querySelector('[data-attr="mock-continue"]')).not.toHaveAttribute('aria-disabled')
            expect(screen.getByText(/You can continue onboarding/)).toBeInTheDocument()
            expect(screen.queryByText('View run')).not.toBeInTheDocument()
            expect(screen.getByLabelText('Copy wizard command')).toBeInTheDocument()
            expect(document.querySelector('[data-attr="sdk-continue"]')).toBeInTheDocument()

            await act(async () => {
                sync.actions.runsLoaded([
                    {
                        ...run,
                        status: 'failed',
                        error_code: 'PHW_DETECT_UNSUPPORTED_VERSION',
                        error_message: 'The project uses an unsupported framework version.',
                    },
                ])
                await expectLogic(sync).toFinishAllListeners()
            })
            expect(screen.getByText('The project uses an unsupported framework version.')).toBeInTheDocument()
            expect(screen.getByText('Update the framework, then run the program again.')).toBeInTheDocument()
            expect(screen.getByLabelText('Copy wizard command')).toBeInTheDocument()
            fireEvent.click(document.querySelector('[data-attr="sdk-continue"]')!)
            expect(screen.getByText('Manual SDK setup')).toBeInTheDocument()
            fireEvent.click(screen.getByLabelText('close'))
            expect(document.querySelector('[data-attr="mock-continue"]')).toHaveAttribute('aria-disabled', 'true')

            await act(async () => {
                sync.actions.runsLoaded([{ ...run, status: 'cancelled' }])
                await expectLogic(sync).toFinishAllListeners()
            })
            expect(screen.getByLabelText('Copy wizard command')).toBeInTheDocument()
            expect(document.querySelector('[data-attr="sdk-continue"]')).toBeInTheDocument()

            await act(async () => {
                sync.actions.runsLoaded([
                    {
                        ...run,
                        id: 'retry',
                        created_at: new Date(Date.now() + 120_000).toISOString(),
                        status: 'completed',
                    },
                ])
                await expectLogic(sync).toFinishAllListeners()
            })
            expect(screen.getByText(/Review the changes in your local project/)).toBeInTheDocument()
            expect(screen.getByLabelText('Copy wizard command')).toBeInTheDocument()
            expect(document.querySelector('[data-attr="mock-continue"]')).not.toHaveAttribute('aria-disabled')

            const pullRequestUrl = 'https://github.com/example/project/pull/12'
            useMocks({
                get: {
                    '/api/projects/:team_id/wizard/runs/cloud-installation/artifacts/': {
                        count: 2,
                        results: [
                            {
                                id: 'diff',
                                team_id: MOCK_DEFAULT_TEAM.id,
                                run_id: 'cloud-installation',
                                artifact_type: 'git_diff',
                                size_bytes: 2048,
                                content_hash: 'example',
                                additions: 1,
                                removals: 0,
                                created_at: createdAt,
                            },
                            {
                                id: 'pr',
                                team_id: MOCK_DEFAULT_TEAM.id,
                                run_id: 'cloud-installation',
                                artifact_type: 'pull_request',
                                url: pullRequestUrl,
                                number: 12,
                                repository: 'example/project',
                                head_branch: 'setup',
                                base_branch: 'main',
                                created_at: createdAt,
                            },
                        ],
                    },
                },
            })
            await act(async () => {
                sync.actions.runsLoaded([
                    {
                        ...run,
                        id: 'cloud-installation',
                        created_at: new Date(Date.now() + 180_000).toISOString(),
                        environment: 'cloud',
                        workspace: { type: 'git_repository', repository: 'example/project' },
                        status: 'completed',
                    },
                ])
                await expectLogic(sync).toFinishAllListeners()
            })
            const reviewLink = screen.getByText('Review pull request').closest('a')
            expect(reviewLink).toHaveAttribute('href', pullRequestUrl)
            expect(reviewLink).toHaveAttribute('target', '_blank')
            expect(screen.getByText('Git diff (2.0 KB)').closest('a')).toBeNull()
            expect(document.querySelector('[data-attr="wizard-install-sync"] a[href*="/wizard/runs"]')).toBeNull()
            fireEvent.click(document.querySelector('[data-attr="wizard-install-artifact"]')!)
            fireEvent.click(reviewLink!)
            for (const clickSource of ['artifact_list', 'review_button']) {
                expect(posthog.capture).toHaveBeenCalledWith(
                    'wizard onboarding state artifact clicked',
                    expect.objectContaining({
                        event_source: 'wizard_ui',
                        project_id: String(MOCK_DEFAULT_TEAM.id),
                        wizard_run_id: 'cloud-installation',
                        task_run_id: 'cloud-installation',
                        environment: 'cloud',
                        program_id: 'posthog-integration',
                        status: 'completed',
                        artifact_type: 'pull_request',
                        artifact_id: 'pr',
                        click_source: clickSource,
                    })
                )
            }
            const artifactEvents = jest
                .mocked(posthog.capture)
                .mock.calls.filter(([event]) => event === 'wizard onboarding state artifact clicked')
            expect(artifactEvents).toHaveLength(2)
            expect(JSON.stringify(artifactEvents)).not.toContain(pullRequestUrl)
        }
    )
})
