import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { AIObservabilityStep } from './AIObservabilityStep'

describe('AIObservabilityStep', () => {
    beforeEach(() => {
        initKeaTests()
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess(MOCK_DEFAULT_TEAM)
    })

    afterEach(() => {
        cleanup()
    })

    it('keeps the chosen language when the provider changes', () => {
        render(<AIObservabilityStep onContinue={jest.fn()} onSkip={jest.fn()} />)

        expect(screen.getByText(/pip install posthog openai/)).toBeInTheDocument()

        fireEvent.click(screen.getAllByText('Node')[0])
        expect(screen.getByText(/npm install @posthog\/ai posthog-node openai/)).toBeInTheDocument()

        fireEvent.click(screen.getAllByText('OpenAI')[0])
        fireEvent.click(screen.getByText('Anthropic'))

        expect(screen.getByText(/npm install @posthog\/ai posthog-node @anthropic-ai\/sdk/)).toBeInTheDocument()
    })
})
