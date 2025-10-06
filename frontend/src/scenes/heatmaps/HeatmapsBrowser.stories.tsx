import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { MockSignature } from '~/mocks/utils'

import heatmapResults from './__mocks__/heatmapResults.json'

const query = (topUrls: [string, number][] = []): MockSignature => {
    return async (req, res, ctx) => {
        const json = await req.clone().json()
        const qry = json.query.query

        // top urls query
        if (qry?.includes('SELECT properties.$current_url AS url, count()')) {
            return res(
                ctx.json({
                    results: topUrls,
                })
            )
        }
        return res(
            ctx.json({
                results: [],
            })
        )
    }
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Heatmaps',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-28', // To stabilize relative dates
        pageUrl: urls.heatmaps(),
        testOptions: {
            waitForLoadersToDisappear: true,
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/integrations': {},
                '/api/heatmap': heatmapResults,
            },
            post: {
                '/api/environments/:team_id/query': query(),
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>
export const HeatmapsBrowserNoPagesAvailable: Story = {}

export function HeatmapsBrowserNoPageSelected(): JSX.Element {
    useStorybookMocks({
        post: {
            '/api/environments/:team_id/query': query([
                ['https://posthog.com/most-views', 100],
                ['https://posthog.com/fewest-views', 50],
            ]),
        },
    })

    return <App />
}

export const HeatmapsBrowserWithUnauthorizedPageSelected: Story = {
    parameters: {
        pageUrl: urls.heatmaps('pageURL=https://random.example.com'),
    },
}

export const HeatmapsBrowserWithPageSelected: Story = {
    parameters: {
        pageUrl: urls.heatmaps('pageURL=https://example.com&heatmapPalette=red&heatmapFilters={"type"%3A"mousemove"}'),
    },
}
