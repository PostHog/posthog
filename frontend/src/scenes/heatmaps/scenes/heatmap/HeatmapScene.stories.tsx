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
                '/api/heatmap': (_req, res, ctx) =>
                    res(
                        ctx.status(200),
                        ctx.json({
                            results: [],
                            count: 0,
                            next: null,
                            previous: null,
                        })
                    ),
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

// 100x100 gray placeholder PNG as data URL (browser can load directly without MSW)
const PLACEHOLDER_IMAGE_DATA_URL =
    'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAGQAAABkCAIAAAD/gAIDAAAAGXRFWHRTb2Z0d2FyZQBBZG9iZSBJbWFnZVJlYWR5ccllPAAAAyJpVFh0WE1MOmNvbS5hZG9iZS54bXAAAAAAADw/eHBhY2tldCBiZWdpbj0i77u/IiBpZD0iVzVNME1wQ2VoaUh6cmVTek5UY3prYzlkIj8+IDx4OnhtcG1ldGEgeG1sbnM6eD0iYWRvYmU6bnM6bWV0YS8iIHg6eG1wdGs9IkFkb2JlIFhNUCBDb3JlIDUuMy1jMDExIDY2LjE0NTY2MSwgMjAxMi8wMi8wNi0xNDo1NjoyNyAgICAgICAgIj4gPHJkZjpSREYgeG1sbnM6cmRmPSJodHRwOi8vd3d3LnczLm9yZy8xOTk5LzAyLzIyLXJkZi1zeW50YXgtbnMjIj4gPHJkZjpEZXNjcmlwdGlvbiByZGY6YWJvdXQ9IiIgeG1sbnM6eG1wPSJodHRwOi8vbnMuYWRvYmUuY29tL3hhcC8xLjAvIiB4bWxuczp4bXBNTT0iaHR0cDovL25zLmFkb2JlLmNvbS94YXAvMS4wL21tLyIgeG1sbnM6c3RSZWY9Imh0dHA6Ly9ucy5hZG9iZS5jb20veGFwLzEuMC9zVHlwZS9SZXNvdXJjZVJlZiMiIHhtcDpDcmVhdG9yVG9vbD0iQWRvYmUgUGhvdG9zaG9wIENTNiAoV2luZG93cykiIHhtcE1NOkluc3RhbmNlSUQ9InhtcC5paWQ6QjRBMTFGNjRCNjJBMTFFNTg4NzM4OENBQTVCOEY1QkYiIHhtcE1NOkRvY3VtZW50SUQ9InhtcC5kaWQ6QjRBMTFGNjVCNjJBMTFFNTg4NzM4OENBQTVCOEY1QkYiPiA8eG1wTU06RGVyaXZlZEZyb20gc3RSZWY6aW5zdGFuY2VJRD0ieG1wLmlpZDpCNEExMUY2MkI2MkExMUU1ODg3Mzg4Q0FBNUI4RjVCRiIgc3RSZWY6ZG9jdW1lbnRJRD0ieG1wLmRpZDpCNEExMUY2M0I2MkExMUU1ODg3Mzg4Q0FBNUI4RjVCRiIvPiA8L3JkZjpEZXNjcmlwdGlvbj4gPC9yZGY6UkRGPiA8L3g6eG1wbWV0YT4gPD94cGFja2V0IGVuZD0iciI/PqqGNnYAAABRSURBVHja7NAxAQAgEMDAL/q3PjFIAhFw6+mc7jMAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABAbwIMALGFAQGC5xnRAAAAAElFTkSuQmCC'

const uploadSaved = {
    id: 102,
    short_id: 'hm_upload',
    name: 'Uploaded screenshot',
    url: '',
    data_url: 'https://app.example.com/dashboard/*',
    target_widths: [],
    type: 'upload',
    status: 'completed',
    has_content: false,
    image_url: PLACEHOLDER_IMAGE_DATA_URL,
    snapshots: [],
    deleted: false,
    created_by: { id: 1, uuid: 'user-1', distinct_id: 'd1', first_name: 'Alice', email: 'alice@ph.com' },
    created_at: '2024-01-04T00:00:00Z',
    updated_at: '2024-01-04T00:00:00Z',
    exception: null,
}

export const UploadExample: Story = {
    parameters: {
        pageUrl: urls.heatmap('hm_upload'),
        testOptions: {
            waitForSelector: '#heatmap-screenshot',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/saved/hm_upload/': uploadSaved,
            },
        }),
    ],
}
