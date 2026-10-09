import type { Meta, StoryObj } from '@storybook/react'
import { screen } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { useEffect } from 'react'

import { ExportType, ExportedData, SharedCanvasPayload, SharedPageViewer } from '~/exporter/types'

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
    shared_at: '2023-01-31T12:00:00Z',
}

const signedOut: SharedPageViewer = {
    is_authenticated: false,
    email: null,
    first_name: null,
    theme_mode: null,
    open_path: null,
    sharing_enabled: true,
    sharing_api_path: null,
    is_creator: false,
}
const creator: SharedPageViewer = {
    is_authenticated: true,
    email: 'ada@example.com',
    first_name: 'Ada',
    theme_mode: 'light',
    open_path: '/desktop/canvas/channel-1/canvas-1',
    sharing_enabled: true,
    sharing_api_path: '/api/projects/1/canvases/canvas-1/sharing',
    is_creator: true,
}

/** A public canvas link: the bar on top, the sandboxed build filling the rest. */
export const SharedCanvas: Story = {
    args: { canvas, viewer: signedOut },
}

/** The share menu open: the link, who it works for, and the way to a copy. */
export const SharedCanvasShareMenu: Story = {
    args: { canvas, viewer: signedOut },
    play: async () => {
        await userEvent.click(await screen.findByText('Share'))
        await screen.findByText('Share canvas')
    },
}

/** The title menu open: where the canvas came from, when it was published, and where a viewer can take it. */
export const SharedCanvasTitleMenu: Story = {
    args: { canvas, viewer: signedOut },
    play: async () => {
        await userEvent.click(await screen.findByText('Premium button'))
        await screen.findByText('Refresh')
    },
}

/** The creator's share menu: the switch that turns the public link on and off, here while it is on. */
export const SharedCanvasShareMenuAsCreator: Story = {
    args: { canvas, viewer: creator },
    play: async () => {
        await userEvent.click(await screen.findByText('Share'))
        await screen.findByText('Public link')
    },
}

/** The link is off: only a member who can open the canvas gets the page, with the switch to turn it back on. */
export const SharedCanvasSharingOff: Story = {
    args: { canvas: { ...canvas, allow_forking: false }, viewer: { ...creator, sharing_enabled: false } },
    play: async () => {
        await userEvent.click(await screen.findByText('Share'))
        await screen.findByText('Public link')
    },
}

/** A signed-in creator gets their account menu instead of a sign-in button, and "by you" in the title menu. */
export const SharedCanvasSignedIn: Story = {
    args: { canvas, viewer: creator },
    play: async () => {
        await userEvent.click(await screen.findByLabelText('Account'))
        await screen.findByText('Sign out')
    },
}

/** The pinned build was cleaned up, so the page says so instead of a blank frame. */
export const SharedCanvasBuildGone: Story = {
    args: { canvas: { ...canvas, published: false, artifact_url: null } },
}

/** A public file link, rendering a markdown file inline. */
export const SharedFile: Story = {
    args: {
        viewer: signedOut,
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
