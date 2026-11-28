import type { WorkOptionApi } from 'products/today/frontend/generated/api.schemas'

import { checkoutWorkThread } from './workThreadFixtures'
import { buildWorkPrompt } from './workThreadPrompt'

function experimentOption(key: string): WorkOptionApi {
    const found = checkoutWorkThread.line.steps[2].options.find((candidate) => candidate.key === key)
    if (!found) {
        throw new Error(`The checkout fixture has no option ${key}`)
    }
    return found
}

describe('workThreadPrompt', () => {
    test.each([
        [
            'names every MCP tool when the helper lists some',
            'ship-winner',
            [
                'In PostHog, for the work thread "New checkout": Ship the winner.',
                '',
                'What this does: Sets the flag to everyone and ends the experiment.',
                'Flag: checkout-v2',
                'Rollout: 100%',
                'Variant: One-page',
                '',
                'Reason: The result is significant and in your favor. More days will add little.',
                '',
                'Use the PostHog MCP server (tools: experiment-ship-variant, feature-flag-roll-out-to-everyone). Show me what you will change and wait for my go-ahead before you change anything users see.',
            ],
        ],
        [
            'leaves out the tool list when the helper lists none',
            'extend-week',
            [
                'In PostHog, for the work thread "New checkout": Extend by a week.',
                '',
                'What this does: Opens the experiment with its end date moved 7 days later.',
                'Experiment: One-page checkout',
                'New end date: In 7 days',
                '',
                'Reason: Weekend traffic is only 1 of the 9 days.',
                '',
                'Use the PostHog MCP server. Show me what you will change and wait for my go-ahead before you change anything users see.',
            ],
        ],
    ])('buildWorkPrompt %s', (_name, optionKey, expectedLines) => {
        expect(buildWorkPrompt(checkoutWorkThread.name, experimentOption(optionKey))).toEqual(expectedLines.join('\n'))
    })
})
