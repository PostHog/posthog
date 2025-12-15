import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const generatingSaved = {
    id: 100,
    short_id: 'hm_gen',
    name: 'Generating…',
    url: 'https://example.com',
    data_url: 'https://example.com',
    target_widths: [768, 1024],
    type: 'screenshot',
    status: 'processing',
    has_content: false,
    snapshots: [],
    deleted: false,
    created_by: { id: 1, uuid: 'user-1', distinct_id: 'd1', first_name: 'Alice', email: 'alice@ph.com' },
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    exception: null,
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Heatmap',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        pageUrl: urls.heatmap('hm_gen'),
        testOptions: {
            waitForLoadersToDisappear: true,
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/saved/hm_gen/': generatingSaved,
                '/api/environments/:team_id/heatmap_screenshots/:id/content/': (_req, res, ctx) =>
                    res(ctx.status(202), ctx.json(generatingSaved)),
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>

export const Generating: Story = {
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}

const iframeSaved = {
    id: 101,
    short_id: 'hm_iframe',
    name: 'Iframe example.com',
    url: 'https://example.com',
    data_url: 'https://example.com',
    target_widths: [],
    type: 'iframe',
    status: 'completed',
    has_content: false,
    snapshots: [],
    deleted: false,
    created_by: { id: 1, uuid: 'user-1', distinct_id: 'd1', first_name: 'Alice', email: 'alice@ph.com' },
    created_at: '2024-01-03T00:00:00Z',
    updated_at: '2024-01-03T00:00:00Z',
    exception: null,
}

export const IframeExample: Story = {
    parameters: {
        pageUrl: urls.heatmap('hm_iframe'),
        testOptions: {
            waitForSelector: '#heatmap-iframe',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/saved/hm_iframe/': iframeSaved,
                'https://example.com': (_req, res, ctx) =>
                    res(
                        ctx.status(200),
                        ctx.set('Content-Type', 'text/html'),
                        ctx.body(`
                            <!DOCTYPE html>
                            <html>
                            <head>
                                <title>Example Domain</title>
                                <style>
                                    body { 
                                        font-family: sans-serif; 
                                        max-width: 800px; 
                                        margin: 50px auto; 
                                        padding: 20px;
                                    }
                                    h1 { color: #333; }
                                    button { 
                                        padding: 10px 20px; 
                                        margin: 10px 5px; 
                                        cursor: pointer;
                                        background: #007bff;
                                        color: white;
                                        border: none;
                                        border-radius: 4px;
                                    }
                                </style>
                            </head>
                            <body>
                                <h1>Example Domain</h1>
                                <p>This domain is for use in illustrative examples in documents.</p>
                                <button id="cta-button">Click me</button>
                                <button id="secondary-button">Learn more</button>
                                <p>You may use this domain in literature without prior coordination or asking for permission.</p>
                            </body>
                            </html>
                        `)
                    ),
            },
        }),
    ],
}

export const New: Story = {
    parameters: {
        pageUrl: urls.heatmap('new'),
    },
}
