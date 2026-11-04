import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SourceTab, TileId } from 'scenes/web-analytics/common'
import { buildDataTableTileDataNodeLogicProps } from 'scenes/web-analytics/tiles/skeletons/useTileSkeletonLoading'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { useMocks } from '~/mocks/jest'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { NodeKind, WebStatsBreakdown } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType } from '~/types'

import { MarketingAnalyticsAdSpendLink } from 'products/web_analytics/frontend/marketing/MarketingAnalyticsAdSpendLink'
import { MarketingAnalyticsCrossSell } from 'products/web_analytics/frontend/marketing/MarketingAnalyticsCrossSell'
import { MarketingAnalyticsFilterHint } from 'products/web_analytics/frontend/marketing/MarketingAnalyticsFilterHint'
import { marketingCrossSellStateLogic } from 'products/web_analytics/frontend/marketing/marketingCrossSellStateLogic'

describe('Marketing analytics cross sell', () => {
    let queries: jest.Mock
    let sources: jest.Mock
    let channel = 'Paid Search'
    let channelRows: [string, [number, null]][] | null = null
    let utmRows: [string, [number, null]][] = []
    let unmount: () => void

    beforeEach(() => {
        localStorage.clear()
        posthog.setPersonProperties = jest.fn()
        channel = 'Paid Search'
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, marketing_analytics_config: {} })
        featureFlagLogic.mount()
        unmount = webAnalyticsLogic.mount()
        channelRows = null
        utmRows = []
        queries = jest.fn(async ({ request }: { request: Request }) => {
            const { query } = await request.clone().json()
            const rows =
                query.breakdownBy === WebStatsBreakdown.InitialUTMSource
                    ? utmRows
                    : (channelRows ?? [[channel, [10, null]]])
            return [200, { columns: ['context.columns.breakdown_value', 'context.columns.visitors'], results: rows }]
        })
        sources = jest.fn(() => [200, { results: [], next: null, count: 0 }])
        useMocks({
            post: { '/api/environments/:team_id/query/:kind/': queries },
            get: { '/api/projects/:team_id/external_data_sources/': sources },
        })
    })
    afterEach(() => {
        cleanup()
        unmount()
    })

    const enable = (setup = false, experimentVariant: 'control' | 'test' = 'control'): void => {
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.WEB_ANALYTICS_MARKETING_CROSS_SELL]: true,
            [FEATURE_FLAGS.MARKETING_ANALYTICS_SETUP]: setup,
            [FEATURE_FLAGS.WEB_ANALYTICS_MARKETING_CROSS_SELL_V2]: experimentVariant,
        })
    }

    const getChannelsNode = (): ReturnType<typeof dataNodeLogic> => {
        const tile = webAnalyticsLogic.values.tiles.find((tile) => tile.tileId === TileId.SOURCES)
        const channel = tile?.kind === 'tabs' ? tile.tabs.find((tab) => tab.id === SourceTab.CHANNEL) : undefined
        if (!channel || channel.query.kind !== NodeKind.DataTableNode) {
            throw new Error('Sources must contain a Channels table')
        }
        return dataNodeLogic(
            buildDataTableTileDataNodeLogicProps({
                query: channel.query,
                insightProps: channel.insightProps,
                context: { insightProps: channel.insightProps },
                uniqueKey: `WebAnalytics.${TileId.SOURCES}.${SourceTab.CHANNEL}`,
            })
        )
    }

    it.each([
        [false, WebStatsBreakdown.InitialChannelType],
        [true, WebStatsBreakdown.InitialReferringDomain],
    ])('does no eligibility work with enabled=%s and breakdown=%s', async (enabled, breakdown) => {
        if (enabled) {
            enable()
        }
        render(<MarketingAnalyticsCrossSell breakdown={breakdown} />)
        await act(async () => {})
        expect(screen.queryByText('Connect ad sources')).toBeNull()
        expect(queries).not.toHaveBeenCalled()
        expect(sources).not.toHaveBeenCalled()
    })

    it.each([
        [false, WebStatsBreakdown.InitialUTMSource],
        [true, WebStatsBreakdown.InitialUTMMedium],
    ])('offers source connection with setup flag=%s on %s', async (setup, breakdown) => {
        enable(setup)
        render(<MarketingAnalyticsCrossSell breakdown={breakdown} />)
        const link = (await screen.findByText('Connect ad sources')).closest('a')!
        const destination = new URL(link.href)
        expect(destination.searchParams.get('date_from')).toBe('-7d')
        expect(destination.searchParams.get('date_to')).toBe('')
        expect(link.getAttribute('href')).toContain('/marketing?')
        expect(link.getAttribute('href')?.includes('tab=setup')).toBe(setup)
        expect(queries).toHaveBeenCalledTimes(1)
        expect(sources).toHaveBeenCalledTimes(1)
        fireEvent.click(screen.getByLabelText('Dismiss Marketing analytics suggestion'))
        expect(screen.queryByText('Connect ad sources')).toBeNull()
        expect(webAnalyticsLogic.values.marketingCrossSellDismissed).toBe(true)
    })

    it('reuses the mounted Channels query without another analytics request', async () => {
        enable()
        const node = getChannelsNode()
        const unmountNode = node.mount()
        try {
            await waitFor(() => expect(node.values.response).not.toBeNull())
            render(<MarketingAnalyticsCrossSell breakdown={WebStatsBreakdown.InitialChannelType} />)
            await screen.findByText('Connect ad sources')
            expect(queries).toHaveBeenCalledTimes(1)
        } finally {
            unmountNode()
        }
    })

    it('offers analysis for a native ad source on a later page', async () => {
        enable()
        sources
            .mockReturnValueOnce([200, { results: [{ source_type: 'Stripe' }], next: 'next', count: 2 }])
            .mockReturnValueOnce([200, { results: [{ source_type: 'GoogleAds' }], next: null, count: 2 }])
        render(<MarketingAnalyticsCrossSell breakdown={WebStatsBreakdown.InitialUTMSourceMediumCampaign} />)
        const link = (await screen.findByText('Analyze in Marketing analytics')).closest('a')!
        const destination = new URL(link.href)
        expect(destination.searchParams.get('date_from')).toBe('-7d')
        expect(destination.searchParams.get('date_to')).toBe('')
        expect(sources).toHaveBeenCalledTimes(2)
    })

    it('does not look up connections for organic traffic', async () => {
        enable()
        channel = 'Organic Search'
        render(<MarketingAnalyticsCrossSell breakdown={WebStatsBreakdown.InitialChannelType} />)
        const node = getChannelsNode()
        await waitFor(() => {
            expect(node.values.responseLoading).toBe(false)
            expect(node.values.response).toMatchObject({ results: [['Organic Search', [10, null]]] })
        })
        expect(queries).toHaveBeenCalledTimes(1)
        expect(screen.queryByText('Connect ad sources')).toBeNull()
        expect(sources).not.toHaveBeenCalled()
    })

    it('keeps the suggestion hidden when the connection check fails', async () => {
        enable()
        sources.mockReturnValue([500, { detail: 'Could not load sources' }])
        render(<MarketingAnalyticsCrossSell breakdown={WebStatsBreakdown.InitialChannelType} />)
        await waitFor(() => expect(sources).toHaveBeenCalledTimes(1))
        await act(async () => {})
        expect(screen.queryByText('Connect ad sources')).toBeNull()
        expect(screen.queryByText('Analyze in Marketing analytics')).toBeNull()
    })

    it('refreshes channel evidence when the date changes on a UTM tab', async () => {
        enable()
        render(<MarketingAnalyticsCrossSell breakdown={WebStatsBreakdown.InitialUTMSource} />)
        await screen.findByText('Connect ad sources')
        const node = getChannelsNode()
        channel = 'Organic Search'
        act(() => webAnalyticsLogic.actions.setDates('-14d', null))
        await waitFor(() => {
            expect(node.values.responseLoading).toBe(false)
            expect(node.values.response).toMatchObject({ results: [['Organic Search', [10, null]]] })
        })
        expect(screen.queryByText('Connect ad sources')).toBeNull()
        expect(queries).toHaveBeenCalledTimes(2)
        expect(sources).toHaveBeenCalledTimes(1)
    })

    it('names the top ad platform in the test arm and snoozes the card on Not now', async () => {
        enable(true, 'test')
        channelRows = [
            ['Paid Search', [120, null]],
            ['Direct', [880, null]],
        ]
        utmRows = [
            ['facebook', [20, null]],
            ['google', [100, null]],
        ]
        render(<MarketingAnalyticsCrossSell breakdown={WebStatsBreakdown.InitialChannelType} />)
        const connect = (await screen.findByText('Connect Google Ads')).closest('a')!
        expect(connect.getAttribute('href')).toContain('/data-warehouse/new-source?kind=GoogleAds')
        expect(screen.getByText('12% of your visitors came from paid ads')).toBeTruthy()
        expect(screen.getByText(/^120 visitors, mostly from Google Ads and Meta Ads\./)).toBeTruthy()
        expect(queries).toHaveBeenCalledTimes(2)
        fireEvent.click(screen.getByLabelText('Not now'))
        expect(screen.queryByText('Connect Google Ads')).toBeNull()
        expect(marketingCrossSellStateLogic({ teamId: MOCK_DEFAULT_TEAM.id }).values.isSnoozed).toBe(true)
    })

    it.each([
        ['below the paid traffic threshold', [['Paid Search', [10, null]] as [string, [number, null]]], 'Stripe'],
        ['with an ad source connected', [['Paid Search', [500, null]] as [string, [number, null]]], 'GoogleAds'],
    ])('shows no card in the test arm %s and skips the UTM lookup', async (_, rows, sourceType) => {
        enable(true, 'test')
        channelRows = rows
        sources.mockReturnValue([200, { results: [{ source_type: sourceType }], next: null, count: 1 }])
        render(<MarketingAnalyticsCrossSell breakdown={WebStatsBreakdown.InitialChannelType} />)
        await waitFor(() => expect(sources).toHaveBeenCalledTimes(1))
        await act(async () => {})
        expect(screen.queryByText(/visitors came from paid ads/)).toBeNull()
        expect(screen.queryByText('Connect ad sources')).toBeNull()
        expect(queries).toHaveBeenCalledTimes(1)
    })

    it('suggests Marketing analytics while a paid UTM source filter is applied, until dismissed', async () => {
        enable(true, 'test')
        render(<MarketingAnalyticsFilterHint teamId={MOCK_DEFAULT_TEAM.id} />)
        expect(screen.queryByText(/You're viewing/)).toBeNull()
        act(() =>
            webAnalyticsLogic.actions.togglePropertyFilter(PropertyFilterType.Session, '$entry_utm_source', 'google')
        )
        expect(await screen.findByText(/You're viewing Google Ads traffic/)).toBeTruthy()
        expect(screen.getAllByText('Connect Google Ads')[0].closest('a')!.getAttribute('href')).toContain(
            '/data-warehouse/new-source?kind=GoogleAds'
        )
        expect(sources).toHaveBeenCalledTimes(1)
        fireEvent.click(screen.getByLabelText('close'))
        expect(screen.queryByText(/You're viewing/)).toBeNull()
        expect(marketingCrossSellStateLogic({ teamId: MOCK_DEFAULT_TEAM.id }).values.isSnoozed).toBe(true)
    })

    it.each([
        ['/web', true],
        ['/marketing', false],
    ])('offers the row action on %s only once connection state is known: %s', async (path, shown) => {
        enable(true, 'test')
        router.actions.push(path)
        let resolveSources: () => void = () => {}
        sources.mockImplementation(
            () =>
                new Promise((resolve) => {
                    resolveSources = () => resolve([200, { results: [], next: null, count: 0 }])
                })
        )
        render(
            <MarketingAnalyticsAdSpendLink
                breakdownBy={WebStatsBreakdown.InitialUTMSource}
                value="google"
                dateRange={null}
            >
                google
            </MarketingAnalyticsAdSpendLink>
        )
        expect(screen.queryByText('See ad spend')).toBeNull()
        if (shown) {
            await waitFor(() => expect(sources).toHaveBeenCalledTimes(1))
            await act(async () => resolveSources())
            const link = (await screen.findByText('See ad spend')).closest('a')!
            expect(link.getAttribute('href')).toContain('/data-warehouse/new-source?kind=GoogleAds')
        } else {
            await act(async () => {})
            expect(screen.queryByText('See ad spend')).toBeNull()
            expect(sources).not.toHaveBeenCalled()
        }
    })
})
