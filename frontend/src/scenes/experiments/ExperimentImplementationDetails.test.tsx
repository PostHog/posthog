import '@testing-library/jest-dom'

import { fireEvent, render, screen } from '@testing-library/react'

import type { Experiment } from '~/types'

import { ExperimentImplementationDetails } from './ExperimentImplementationDetails'

const PROMPT_EXPERIMENT = {
    feature_flag: { key: 'my-prompt-experiment' },
    parameters: {
        prompt_metadata: { name: 'support-reply', templates: ['support-reply'], versions: [1, 2] },
    },
} as unknown as Experiment

describe('ExperimentImplementationDetails', () => {
    // The agent prompt runs past 50 lines. Without the collapse it pushes the rest of the page
    // out of view, so the snippet must open collapsed and only unfold when the user asks.
    it('collapses the agent prompt until expanded', () => {
        render(<ExperimentImplementationDetails experiment={PROMPT_EXPERIMENT} />)

        expect(screen.queryByText(/Reference docs/)).not.toBeInTheDocument()

        fireEvent.click(screen.getByRole('button', { name: /more lines/ }))

        expect(screen.getByText(/Reference docs/)).toBeInTheDocument()
    })
})
