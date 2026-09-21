import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { router } from 'kea-router'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { InsightScene } from './InsightScene'

jest.mock('scenes/insights/InsightAsScene', () => ({ InsightAsScene: () => null }))
jest.mock('products/posthog_ai/frontend/api/logics', () => ({ useAttachedContext: jest.fn() }))

describe('InsightScene', () => {
    afterEach(cleanup)

    it.each([
        ['missing subscription', 404, {}, false],
        ['matching subscription', 200, { id: 123, insight_short_id: 'missing1', deleted: false }, true],
        ['different parent insight', 200, { id: 123, insight_short_id: 'another1', deleted: false }, false],
        ['failed subscription lookup', 500, {}, false],
    ])('replaces the skeleton for a missing insight with a %s', async (_name, status, subscription, canOpen) => {
        useMocks({
            get: {
                '/api/environments/:team_id/insights/': { count: 0, results: [] },
                '/api/projects/:team_id/subscriptions/123/': () => [status, subscription],
            },
        })
        initKeaTests()
        router.actions.push('/insights/missing1/subscriptions/123')

        render(<InsightScene />)

        expect(screen.getAllByText('Loading…').length).toBeGreaterThan(0)
        expect(await screen.findByText('Insight not found')).toBeInTheDocument()
        expect(screen.queryByText('Loading…')).not.toBeInTheDocument()
        if (canOpen) {
            expect(screen.getByRole('link', { name: 'Open subscription' })).toHaveAttribute(
                'href',
                '/project/997/subscriptions/123'
            )
            expect(
                screen.getByText('Subscriptions do not send reports for deleted insights.', { exact: false })
            ).toBeInTheDocument()
        } else {
            expect(screen.queryByRole('link', { name: 'Open subscription' })).not.toBeInTheDocument()
        }
    })
})
