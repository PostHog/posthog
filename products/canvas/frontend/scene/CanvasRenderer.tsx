import { BindLogic, useValues } from 'kea'

import type { CanvasCapabilitiesApi } from '../generated/api.schemas'
import { CanvasHostLogicProps, canvasHostLogic } from '../host/canvasHostLogic'
import { CanvasHostPromptDialog } from '../host/CanvasHostPromptDialog'
import { CanvasHostFrame } from './CanvasHostFrame'
import { CanvasRenderSource, canvasSceneLogic } from './canvasSceneLogic'

/** Renders a build when there is one, else the source in the draft sandbox. */
export function CanvasRenderer({ source }: { source: CanvasRenderSource }): JSX.Element | null {
    const { canvas, sandboxDocumentUrl } = useValues(canvasSceneLogic)
    if (!canvas) {
        return null
    }
    const hostProps: CanvasHostLogicProps = {
        canvasId: canvas.id,
        spaceId: canvas.channel,
        sourceVersionId: source.sourceVersionId,
    }
    return (
        <BindLogic logic={canvasHostLogic} props={hostProps}>
            <CanvasHostFrame
                hostProps={hostProps}
                artifactUrl={source.build?.artifact_url ?? null}
                capabilities={(source.build?.manifest?.capabilities as CanvasCapabilitiesApi | undefined) ?? null}
                buildId={source.build?.id ?? null}
                draftSource={source.draftSource}
                sandboxDocumentUrl={sandboxDocumentUrl}
            />
            <CanvasHostPromptDialog />
        </BindLogic>
    )
}
