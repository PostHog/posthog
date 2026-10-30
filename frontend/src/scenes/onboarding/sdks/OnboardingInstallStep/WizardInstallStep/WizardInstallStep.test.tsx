import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

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
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/event_definitions': { results: [], count: 0 },
            },
            post: {
                '/api/environments/:team_id/query': { results: [] },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('shows the ai-observability command and blocks Continue until installation completes', async () => {
        render(
            <Provider>
                <WizardInstallStep {...AIO_PROPS} />
            </Provider>
        )

        expect(await screen.findByText((t) => t.includes('ai-observability') && t.includes('npx'))).toBeInTheDocument()
        expect(document.querySelector('[data-attr="mock-continue"]')).toHaveAttribute('aria-disabled', 'true')
    })
})
