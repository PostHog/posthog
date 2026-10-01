import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { useCallback } from 'react'

import { themeLogic } from 'lib/logic/themeLogic'

import type { CanvasCapabilitiesApi, CanvasSourceProjectApi } from '../generated/api.schemas'
import { BuiltCanvas } from '../host/BuiltCanvas'
import {
    CanvasHostLogicProps,
    canvasHasUserActivation,
    canvasHostLogic,
    handleCanvasDataRequest,
} from '../host/canvasHostLogic'
import { CanvasHostPromptDialog } from '../host/CanvasHostPromptDialog'
import { DraftCanvas } from '../host/DraftCanvas'
import { canvasSceneLogic } from './canvasSceneLogic'

/** Renders the live build when there is one, else the head source in the draft sandbox. */
export function CanvasRenderer(): JSX.Element | null {
    const { canvas, liveBuild, sandboxDocumentUrl, view } = useValues(canvasSceneLogic)
    if (!canvas) {
        return null
    }
    const hostProps: CanvasHostLogicProps = {
        canvasId: canvas.id,
        spaceId: canvas.channel,
        sourceVersionId: liveBuild ? liveBuild.source_version_id : (view?.current_version_id ?? null),
    }
    return (
        <BindLogic logic={canvasHostLogic} props={hostProps}>
            <CanvasHostFrame
                hostProps={hostProps}
                artifactUrl={liveBuild?.artifact_url ?? null}
                capabilities={(liveBuild?.manifest?.capabilities as CanvasCapabilitiesApi | undefined) ?? null}
                buildId={liveBuild?.id ?? null}
                draftSource={view?.source ?? null}
                sandboxDocumentUrl={sandboxDocumentUrl}
            />
            <CanvasHostPromptDialog />
        </BindLogic>
    )
}

function CanvasHostFrame({
    hostProps,
    artifactUrl,
    capabilities,
    buildId,
    draftSource,
    sandboxDocumentUrl,
}: {
    hostProps: CanvasHostLogicProps
    artifactUrl: string | null
    capabilities: CanvasCapabilitiesApi | null
    buildId: string | null
    draftSource: CanvasSourceProjectApi | null
    sandboxDocumentUrl: string | null
}): JSX.Element | null {
    const hostLogic = useMountedLogic(canvasHostLogic(hostProps))
    const { navigate, openExternal, canvasRendered, canvasErrored } = useActions(hostLogic)
    const { isDarkModeOn } = useValues(themeLogic)
    const theme = isDarkModeOn ? 'dark' : 'light'
    const onDataRequest = useCallback(
        (method: string, payload: unknown) => handleCanvasDataRequest(hostLogic, method, payload),
        [hostLogic]
    )
    const shared = {
        theme,
        onDataRequest,
        onNavigate: navigate,
        onOpenExternal: openExternal,
        onRendered: () => canvasRendered(buildId),
        onError: (message: string) => canvasErrored(message, buildId),
        hasUserActivation: canvasHasUserActivation,
    } as const

    if (artifactUrl) {
        // Keyed by build, so a new live build gets a fresh frame and bridge.
        return (
            <BuiltCanvas
                key={buildId ?? artifactUrl}
                artifactUrl={artifactUrl}
                capabilities={capabilities}
                {...shared}
            />
        )
    }
    if (draftSource?.files['src/canvas.tsx'] && sandboxDocumentUrl) {
        return (
            <DraftCanvas
                documentUrl={sandboxDocumentUrl}
                files={draftSource.files}
                entry="src/canvas.tsx"
                {...shared}
            />
        )
    }
    return null
}
