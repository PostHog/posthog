import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import type { DangerousOperationResponse } from '~/queries/schema/schema-assistant-messages'

import { DangerousOperationInput } from './DangerousOperationInput'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useActions: jest.fn(),
    useValues: jest.fn(),
}))

jest.mock('../maxThreadLogic', () => ({
    maxThreadLogic: { __mock: 'maxThreadLogic' },
}))

jest.mock('products/posthog_ai/frontend/api/primitives', () => ({
    MarkdownMessage: ({ content }: { content: string }) => <div>{content}</div>,
    OptionSelector: ({ options, onSelect }: { options: { label: string; value: string }[]; onSelect: (value: string) => void }) => (
        <div>
            {options.map((option) => (
                <button key={option.value} onClick={() => onSelect(option.value)}>
                    {option.label}
                </button>
            ))}
        </div>
    ),
}))

describe('DangerousOperationInput', () => {
    const continueAfterApproval = jest.fn()
    const continueAfterApprovals = jest.fn()
    const continueAfterRejection = jest.fn()

    const insightOperations: DangerousOperationResponse[] = [
        {
            status: 'pending_approval',
            proposalId: 'proposal-1',
            toolName: 'create_insight',
            preview: 'Update insight one',
            payload: {},
        },
        {
            status: 'pending_approval',
            proposalId: 'proposal-2',
            toolName: 'create_insight',
            preview: 'Update insight two',
            payload: {},
        },
    ]

    beforeEach(() => {
        jest.clearAllMocks()
        ;(useActions as jest.Mock).mockReturnValue({
            continueAfterApproval,
            continueAfterApprovals,
            continueAfterRejection,
        })
        ;(useValues as jest.Mock).mockReturnValue({ streamingActive: false })
    })

    afterEach(() => cleanup())

    it('shows every pending insight preview and approves them together', () => {
        render(<DangerousOperationInput operations={insightOperations} />)

        expect(screen.getByText('Update insight one')).toBeInTheDocument()
        expect(screen.getByText('Update insight two')).toBeInTheDocument()
        fireEvent.click(screen.getByRole('button', { name: 'Approve all 2 insight edits' }))

        expect(continueAfterApprovals).toHaveBeenCalledWith(['proposal-1', 'proposal-2'])
        expect(continueAfterApproval).not.toHaveBeenCalled()
    })

    it('does not offer bulk approval when a pending operation is not an insight edit', () => {
        render(
            <DangerousOperationInput
                operations={[
                    ...insightOperations,
                    {
                        status: 'pending_approval',
                        proposalId: 'proposal-3',
                        toolName: 'create_experiment',
                        preview: 'Create experiment',
                        payload: {},
                    },
                ]}
            />
        )

        expect(screen.queryByRole('button', { name: /Approve all/ })).not.toBeInTheDocument()
    })
})
