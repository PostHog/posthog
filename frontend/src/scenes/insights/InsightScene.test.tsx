import { cleanup, render, screen, waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { InsightShortId, ItemMode } from '~/types'

import { InsightScene } from './InsightScene'
import { insightSceneLogic } from './insightSceneLogic'

jest.mock('scenes/insights/InsightAsScene', () => ({ InsightAsScene: () => null }))

const Insight42 = 'ii42' as InsightShortId

describe('InsightScene', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    const mountScene = (): void => {
        insightSceneLogic.mount()
        insightSceneLogic.actions.setSceneState(
            Insight42,
            ItemMode.View,
            undefined,
            undefined,
            undefined,
            undefined,
            undefined,
            undefined,
            undefined,
            null
        )
        render(<InsightScene />)
    }

    // A 500 on the insight read used to land on the "not found" screen, which told the user their
    // insight was gone and gave them no way to retry.
    it('shows a retryable error when the insight read fails on the server', async () => {
        useMocks({ get: { '/api/environments/:team_id/insights/': () => [500, ''] } })
        mountScene()

        await waitFor(() => expect(screen.getByText("Couldn't load this insight")).toBeTruthy())
        expect(screen.getByText(/HTTP 500/)).toBeTruthy()
        expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy()
        expect(screen.queryByText('Insight not found')).toBeNull()
    })

    it('still shows not found when the insight does not exist', async () => {
        useMocks({ get: { '/api/environments/:team_id/insights/': () => [200, { results: [] }] } })
        mountScene()

        await waitFor(() => expect(screen.getByText('Insight not found')).toBeTruthy())
    })
})
