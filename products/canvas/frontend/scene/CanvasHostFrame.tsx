import { useActions, useMountedLogic, useValues } from 'kea'
import { useCallback, useEffect } from 'react'

import { themeLogic } from 'lib/logic/themeLogic'

import type { CanvasCapabilitiesApi, CanvasSourceProjectApi } from '../generated/api.schemas'
import { BuiltCanvas } from '../host/BuiltCanvas'
import {
    CanvasHostLogicProps,
    canvasHasUserActivation,
    canvasHostLogic,
    handleCanvasDataRequest,
} from '../host/canvasHostLogic'
import type { CanvasRect } from '../host/canvasProtocol'
import { DraftCanvas } from '../host/DraftCanvas'
import { canvasCommentsLogic } from '../sidePanel/comments/canvasCommentsLogic'
import { canvasSceneLogic } from './canvasSceneLogic'

export interface CanvasHostFrameProps {
    hostProps: CanvasHostLogicProps
    artifactUrl: string | null
    capabilities: CanvasCapabilitiesApi | null
    buildId: string | null
    draftSource: CanvasSourceProjectApi | null
    sandboxDocumentUrl: string | null
}

/** One rendered canvas, a build or a draft, wired to the host bridge, runtime errors, and comments. */
export function CanvasHostFrame({
    hostProps,
    artifactUrl,
    capabilities,
    buildId,
    draftSource,
    sandboxDocumentUrl,
}: CanvasHostFrameProps): JSX.Element | null {
    const hostLogic = useMountedLogic(canvasHostLogic(hostProps))
    const { navigate, openExternal, canvasRendered, canvasErrored } = useActions(hostLogic)
    const { setRuntimeError } = useActions(canvasSceneLogic)
    const { highlights, clearTextSelectionKey, commentsEnabled } = useValues(canvasCommentsLogic)
    const { setTextSelection, activateThread } = useActions(canvasCommentsLogic)
    const { isDarkModeOn } = useValues(themeLogic)
    const theme = isDarkModeOn ? 'dark' : 'light'
    const onDataRequest = useCallback(
        (method: string, payload: unknown) => handleCanvasDataRequest(hostLogic, method, payload),
        [hostLogic]
    )
    // A build's "rendered" signal is its load event, which fires after a render that threw, so only
    // a new build or new source clears the last error.
    useEffect(() => {
        setRuntimeError(null)
    }, [buildId, draftSource, setRuntimeError])

    const shared = {
        theme,
        onDataRequest,
        onNavigate: navigate,
        onOpenExternal: openExternal,
        onRendered: () => canvasRendered(buildId),
        onError: (message: string) => {
            setRuntimeError(message)
            canvasErrored(message, buildId)
        },
        onTextSelection: commentsEnabled ? setTextSelection : undefined,
        onTextSelectionCleared: () => setTextSelection(null),
        onCommentActivate: commentsEnabled
            ? (id: string, rect: CanvasRect | null) => activateThread(id, rect, 'highlight')
            : undefined,
        commentHighlights: highlights,
        clearTextSelectionKey,
        hasUserActivation: canvasHasUserActivation,
    } as const

    if (artifactUrl) {
        // Keyed by build, so a new build gets a fresh frame and bridge.
        return (
            <BuiltCanvas
                key={buildId ?? artifactUrl}
                artifactUrl={artifactUrl}
                capabilities={capabilities}
                {...shared}
            />
        )
    }
    if (draftSource && sandboxDocumentUrl) {
        return (
            <DraftCanvas
                documentUrl={sandboxDocumentUrl}
                capabilities={draftSource.capabilities}
                files={draftSource.files}
                entry="src/canvas.tsx"
                {...shared}
            />
        )
    }
    return null
}
