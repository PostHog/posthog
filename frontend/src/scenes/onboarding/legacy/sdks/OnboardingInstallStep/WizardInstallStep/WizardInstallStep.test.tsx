import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { activeCloudRunLogic } from 'scenes/onboarding/shared/wizard-sync/activeCloudRunLogic'
import { projectLogic } from 'scenes/projectLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { VERIFY_AI_EVENTS } from '../../hooks/useInstallationComplete'
import { VariantProps } from '../types'
import { WizardInstallStep } from './index'

// The run block's internals (session stream) are irrelevant here — the assertion is which
// branch renders, so a marker stub keeps jsdom out of SSE territory.
jest.mock('scenes/onboarding/shared/wizard-sync/WizardCloudRunBlock', () => ({
    WizardCloudRunBlock: () => <div data-attr="mock-cloud-run-block" />,
}))

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

// Manual-setup surfaces (behind a modal that stays closed) and the sync progress view — not under test.
jest.mock('../SDKGrid', () => ({ SDKGrid: () => null }))
jest.mock('../SDKInstructionsModal', () => ({ SDKInstructionsModal: () => null }))
jest.mock('scenes/onboarding/shared/wizard-sync/InstallationProgressView', () => ({
    InstallationProgressView: () => null,
}))

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
    let projectId: number

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/event_definitions': { results: [], count: 0 },
                '/api/projects/:project_id/tasks/active_wizard_run/': {
                    task_id: 'task-from-earlier-step',
                    run_id: 'run-from-earlier-step',
                    status: 'running',
                    started_at: '2026-08-06T00:00:00Z',
                },
            },
            post: {
                '/api/environments/:team_id/query': { results: [] },
            },
        })
        initKeaTests()
        projectLogic.mount()
        projectId = projectLogic.values.currentProjectId as number
        activeCloudRunLogic.mount()
    })

    afterEach(() => {
        activeCloudRunLogic.actions.clearActiveCloudRun()
        cleanup()
    })

    it('without an active cloud run: shows the ai-observability command and blocks Continue', async () => {
        render(
            <Provider>
                <WizardInstallStep {...AIO_PROPS} />
            </Provider>
        )

        expect(await screen.findByText((t) => t.includes('ai-observability') && t.includes('npx'))).toBeInTheDocument()
        expect(document.querySelector('[data-attr="mock-cloud-run-block"]')).toBeNull()

        expect(document.querySelector('[data-attr="mock-continue"]')).toHaveAttribute('aria-disabled', 'true')
    })

    it('ignores a cloud run queued on an earlier install step: command stays, Continue stays blocked', async () => {
        // The base-program run the user queued on the posthog-js install step of the same flow. It
        // must not replace the dedicated ai-observability command or satisfy the continue gate.
        activeCloudRunLogic.actions.setActiveCloudRun(
            'task-from-earlier-step',
            'run-from-earlier-step',
            '2026-08-06T00:00:00Z',
            projectId
        )

        render(
            <Provider>
                <WizardInstallStep {...AIO_PROPS} />
            </Provider>
        )

        expect(await screen.findByText((t) => t.includes('ai-observability') && t.includes('npx'))).toBeInTheDocument()
        expect(document.querySelector('[data-attr="mock-cloud-run-block"]')).toBeNull()

        expect(document.querySelector('[data-attr="mock-continue"]')).toHaveAttribute('aria-disabled', 'true')
    })
})
