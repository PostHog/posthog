import { Meta } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const meta: Meta = {
    title: 'Scenes-App/Heatmaps',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-28', // To stabilize relative dates
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/integrations': {},
            },
            post: {
                '/api/projects/:team_id/query': async (req, res, ctx) => {
                    const qry = (await req.clone().json()).query.query
                    // top urls query
                    if (qry.startsWith('SELECT properties.$current_url AS url, count()')) {
                        return res(
                            ctx.json({
                                results: [
                                    ['https://example.io/most-views', 100],
                                    ['https://example.com/fewest-views', 50],
                                ],
                            })
                        )
                    }
                    return res(
                        ctx.json({
                            results: [],
                        })
                    )
                },
            },
        }),
    ],
}
export default meta

export function HeatmapsBrowserNoPageSelected(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.heatmaps())
    }, [])
    return <App />
}
