import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { webPath } from './webPath'

export interface CodeCanvasLinkProps {
    channelId: string
    dashboardId: string
}

export const scene: SceneExport<CodeCanvasLinkProps> = {
    component: CodeCanvasLink,
    paramsToProps: ({ params: { channelId, dashboardId } }) => ({
        channelId: channelId ?? '',
        dashboardId: dashboardId ?? '',
    }),
}

/**
 * Public entry point for canvas share links (`/code/canvas/<channelId>/<dashboardId>`).
 * The link shape stays because released desktop apps parse it, but in the browser it
 * always opens the canvas in the web app.
 */
export function CodeCanvasLink({ dashboardId }: CodeCanvasLinkProps): JSX.Element {
    const { location } = useValues(router)
    const webUrl = dashboardId ? webPath(location.pathname, urls.canvasDetail(dashboardId)) : null

    useEffect(() => {
        if (webUrl) {
            // A full page load, because a client-side route change skips the server login gate
            // and a signed-out visitor would see a blank page instead of the login page.
            window.location.replace(webUrl)
        }
    }, [webUrl])

    return <SpinnerOverlay sceneLevel />
}

export default CodeCanvasLink
