import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { useCallback } from 'react'

import { themeLogic } from 'lib/logic/themeLogic'

import {
    CanvasHostLogicProps,
    canvasHasUserActivation,
    canvasHostLogic,
    handleCanvasDataRequest,
} from '../host/canvasHostLogic'
import { CanvasHostPromptDialog } from '../host/CanvasHostPromptDialog'
import { canvasSceneLogic } from '../scene/canvasSceneLogic'
import { canvasEditLogic } from './canvasEditLogic'
import { CanvasSourceEditor } from './CanvasSourceEditor'

function EditorFrame({
    hostProps,
    documentUrl,
}: {
    hostProps: CanvasHostLogicProps
    documentUrl: string
}): JSX.Element {
    const hostLogic = useMountedLogic(canvasHostLogic(hostProps))
    const { navigate, openExternal, canvasErrored } = useActions(hostLogic)
    const { setRuntimeError } = useActions(canvasSceneLogic)
    const { isDarkModeOn } = useValues(themeLogic)
    const onDataRequest = useCallback(
        (method: string, payload: unknown) => handleCanvasDataRequest(hostLogic, method, payload),
        [hostLogic]
    )
    return (
        <CanvasSourceEditor
            documentUrl={documentUrl}
            theme={isDarkModeOn ? 'dark' : 'light'}
            hasUserActivation={canvasHasUserActivation}
            onOpenExternal={openExternal}
            onDataRequest={onDataRequest}
            onNavigate={navigate}
            // Each edit remounts the source, so a clean render clears the last error.
            onRendered={() => setRuntimeError(null)}
            onError={(message) => {
                setRuntimeError(message)
                canvasErrored(message, null)
            }}
        />
    )
}

/** The canvas body in edit mode: the head source in the editable sandbox, wired to the host bridge. */
export function CanvasEditorRenderer(): JSX.Element | null {
    const { canvas, sandboxDocumentUrl } = useValues(canvasSceneLogic)
    const { entry } = useValues(canvasEditLogic)
    if (!canvas || !sandboxDocumentUrl || !entry) {
        return null
    }
    const hostProps: CanvasHostLogicProps = {
        canvasId: canvas.id,
        spaceId: canvas.channel,
        sourceVersionId: entry.baseVersionId,
    }
    return (
        <BindLogic logic={canvasHostLogic} props={hostProps}>
            <EditorFrame hostProps={hostProps} documentUrl={sandboxDocumentUrl} />
            <CanvasHostPromptDialog />
        </BindLogic>
    )
}
