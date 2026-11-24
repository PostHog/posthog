import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'
import { Survey, SurveyMatchType, SurveyType } from '~/types'

import { surveysSiteSnapshotRetrieve } from 'products/surveys/frontend/generated/api'
import type { SiteSnapshotApi } from 'products/surveys/frontend/generated/api.schemas'

import { useSiteThemeCard } from './SiteThemeCard'

jest.mock('products/surveys/frontend/generated/api', () => ({
    ...jest.requireActual('products/surveys/frontend/generated/api'),
    surveysSiteSnapshotRetrieve: jest.fn(),
}))

const mockRetrieve = surveysSiteSnapshotRetrieve as jest.MockedFunction<typeof surveysSiteSnapshotRetrieve>

const RENDERING: SiteSnapshotApi = {
    status: 'rendering',
    exported_asset_id: 7,
    page_url: 'https://example.com/pricing',
    viewport_width: 1440,
    site_style: null,
}

function Card({ url }: { url: string }): JSX.Element | null {
    return useSiteThemeCard({
        survey: {
            id: 'survey-id',
            type: SurveyType.Popover,
            conditions: { url, urlMatchType: SurveyMatchType.Contains },
        } as unknown as Survey,
        appearance: {},
        onSelectTheme: () => {},
    })
}

async function advance(ms: number): Promise<void> {
    await act(async () => {
        await jest.advanceTimersByTimeAsync(ms)
    })
}

describe('SiteThemeCard', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.SURVEYS_MATCH_MY_SITE]: true })
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({ ...teamLogic.values.currentTeam!, session_recording_opt_in: true })
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    it.each([
        ['no answer yet', () => new Promise<SiteSnapshotApi>(() => {}), 5_000, 'Finding a recent visit'],
        ['a render in progress', async () => RENDERING, 12_000, "Reading your site's colors"],
        ['a slow render', async () => RENDERING, 40_000, 'Taking longer than usual'],
        [
            'a request that keeps failing',
            async () => Promise.reject(new Error('offline')),
            40_000,
            'Taking longer than usual',
        ],
    ])('describes %s', async (_name, respond, elapsedMs, copy) => {
        mockRetrieve.mockImplementation(respond)
        render(<Card url="pricing" />)
        fireEvent.click(screen.getByText("Use your site's colors"))

        await advance(elapsedMs)

        expect(screen.getByText(copy)).toBeInTheDocument()
        expect(screen.getByText(`${Math.floor(elapsedMs / 1000)}s`)).toBeInTheDocument()
    })

    it('starts over when the URL targeting changes', async () => {
        mockRetrieve.mockImplementation(async () => RENDERING)
        const { rerender } = render(<Card url="pricing" />)
        fireEvent.click(screen.getByText("Use your site's colors"))
        await advance(40_000)

        mockRetrieve.mockImplementation(() => new Promise(() => {}))
        rerender(<Card url="docs" />)
        await advance(1_000)

        expect(screen.getByText('Finding a recent visit')).toBeInTheDocument()
        expect(screen.getByText('1s')).toBeInTheDocument()
    })
})
