import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import type { SandboxToolCallMessage } from '../maxTypes'
import { SandboxQuestionRenderer } from './SandboxQuestionRenderer'

function makeMessage(overrides: Partial<SandboxToolCallMessage> = {}): SandboxToolCallMessage {
    return {
        id: 'tc-1',
        resolvedKey: 'AskUserQuestion',
        rawServerName: '',
        rawToolName: 'AskUserQuestion',
        claudeToolName: 'AskUserQuestion',
        rawInput: {
            questions: [
                {
                    question: 'Which goal matters most?',
                    header: 'Goal',
                    multiSelect: false,
                    options: [{ label: 'Activation' }, { label: 'Revenue' }],
                },
            ],
        },
        content: [],
        status: 'completed',
        ...overrides,
    }
}

function renderCard(message: SandboxToolCallMessage): void {
    render(<SandboxQuestionRenderer message={message} isLastInGroup displayName="Question" />)
}

describe('SandboxQuestionRenderer', () => {
    afterEach(() => {
        cleanup()
    })

    it('renders the question and the chosen answer once answered, without the per-question header chip', () => {
        renderCard(makeMessage({ rawOutput: { answers: { 'Which goal matters most?': 'Revenue' } } }))

        expect(screen.getByText('Which goal matters most?')).toBeInTheDocument()
        expect(screen.getByText('Revenue')).toBeInTheDocument()
        expect(screen.getByText('Revenue')).toHaveClass('font-medium')
        // The header label ("Goal") is dropped from the recap — the answer carries the meaning.
        expect(screen.queryByText('Goal')).not.toBeInTheDocument()
    })

    it('does not render the question in place while it is still being asked', () => {
        renderCard(makeMessage({ status: 'in_progress', rawOutput: undefined }))

        // The overlay owns the unanswered state; the recap body stays empty until an answer arrives.
        expect(screen.queryByText('Which goal matters most?')).not.toBeInTheDocument()
        expect(screen.queryByText('Waiting for your answer…')).not.toBeInTheDocument()
    })

    it('recaps each answer for a multi-question request', () => {
        renderCard(
            makeMessage({
                rawInput: {
                    questions: [
                        { question: 'Goal?', header: 'Goal', multiSelect: false, options: [{ label: 'Revenue' }] },
                        { question: 'When?', header: 'When', multiSelect: false, options: [{ label: 'Weekly' }] },
                    ],
                },
                rawOutput: { answers: { 'Goal?': 'Revenue', 'When?': 'Weekly' } },
            })
        )

        expect(screen.getByText('Revenue')).toBeInTheDocument()
        expect(screen.getByText('Weekly')).toBeInTheDocument()
    })

    it('falls back to a joined answer string when there is no per-question map', () => {
        renderCard(makeMessage({ rawOutput: { text: 'User picked Revenue' } }))

        expect(screen.getByText('User picked Revenue')).toBeInTheDocument()
    })

    it('shows the error message when the call failed', () => {
        renderCard(makeMessage({ status: 'failed', rawOutput: undefined, error: { message: 'Question timed out' } }))

        expect(screen.getByText('Question timed out')).toBeInTheDocument()
    })

    it('falls back to the generic tool card when the input has no questions', () => {
        renderCard(makeMessage({ rawInput: {}, rawOutput: undefined }))

        // The generic card renders instead of the question recap.
        expect(screen.getByText('Question')).toBeInTheDocument()
        expect(screen.queryByText('Which goal matters most?')).not.toBeInTheDocument()
    })
})
