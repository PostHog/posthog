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

    it('replaces the skeleton with not found when a directly opened subscription has no parent insight', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/insights/': { count: 0, results: [] },
            },
        })
        initKeaTests()
        router.actions.push('/insights/missing1/subscriptions/123')

        render(<InsightScene />)

        expect(screen.getAllByText('Loading…').length).toBeGreaterThan(0)
        expect(await screen.findByText('Insight not found')).toBeInTheDocument()
        expect(screen.queryByText('Loading…')).not.toBeInTheDocument()
    })
})
