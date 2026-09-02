import type { Experiment } from '~/types'

import { NEW_EXPERIMENT } from 'products/experiments/frontend/constants'

import { experimentScannerPrompt } from './replayVisionScanner'

describe('experimentScannerPrompt', () => {
    it.each([
        {
            name: 'uses the hypothesis as the changed-surface grounding',
            description: 'New one-page checkout',
            expected: 'What the experiment changes: New one-page checkout',
        },
        {
            name: 'falls back to the experiment name when the hypothesis is blank',
            description: '',
            expected: 'Its name is "Checkout redesign"',
        },
        {
            name: 'treats a whitespace-only hypothesis as blank',
            description: '   ',
            expected: 'Its name is "Checkout redesign"',
        },
    ])('$name', ({ description, expected }) => {
        const experiment: Experiment = { ...NEW_EXPERIMENT, name: 'Checkout redesign', description }
        expect(experimentScannerPrompt(experiment)).toContain(expected)
    })
})
