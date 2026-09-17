import type { Meta, StoryObj } from '@storybook/react'
import { useEffect } from 'react'

import { ExportType, ExportedData, SharedCanvasPayload } from '~/exporter/types'

import { Exporter } from '../Exporter'

type Story = StoryObj<ExportedData>
const meta: Meta<ExportedData> = {
    title: 'Exporter/Shared',
    component: Exporter,
    args: {
        type: ExportType.Scene,
        whitelabel: false,
        accessToken: 'share-token',
    },
    parameters: {
        testOptions: {
            snapshotBrowsers: ['chromium'],
        },
        mockDate: '2023-02-01',
        viewMode: 'story',
        layout: 'fullscreen',
    },
    tags: [], // Omit 'autodocs', as it's broken with Exporter
    render: (props) => {
        useEffect(() => {
            document.body.className = ''
            document.documentElement.className = `export-type-${props.type}`
        }, [props.type])
        return <Exporter {...props} />
    },
}

export default meta

// A stand-in for the published build: the real one is a signed URL on the artifact origin.
const CANVAS_BUILD_URL =
    'data:text/html,' +
    encodeURIComponent(
        '<!doctype html><body style="margin:0;height:100vh;display:grid;place-items:center;background:#1c1c1c;color:#eee;font:16px sans-serif">The published canvas build renders here</body>'
    )

const canvas: SharedCanvasPayload = {
    id: 'canvas-1',
    name: 'Premium button',
    kind: 'freeform',
    description: 'A polished interactive button canvas.',
    published: true,
    artifact_url: CANVAS_BUILD_URL,
    allow_forking: true,
}

/** A public canvas link: the bar on top, the sandboxed build filling the rest. */
export const SharedCanvas: Story = {
    args: { canvas },
}

/** The pinned build was cleaned up, so the page says so instead of a blank frame. */
export const SharedCanvasBuildGone: Story = {
    args: { canvas: { ...canvas, published: false, artifact_url: null } },
}

/** A public file link, rendering a markdown file inline. */
export const SharedFile: Story = {
    args: {
        task_artifact: {
            name: 'release-notes.md',
            content_type: 'text/markdown',
            kind: 'markdown',
            size: 1834,
            uploaded_at: '2023-01-31T12:00:00Z',
            markdown:
                '# Release notes\n\nThe agent wrote this file during the run.\n\n- Sharing pins the upload the link shows\n- Later uploads stay private until they are published\n',
            file_url: '/shared/share-token.md',
        },
    },
}
