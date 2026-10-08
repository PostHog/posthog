import { useActions, useValues } from 'kea'

import { Button } from '@posthog/quill'

import { canvasHistoryLogic } from '../history/canvasHistoryLogic'
import { DATA_DRIFT_ERROR_TYPE, canvasSceneLogic } from './canvasSceneLogic'
import { CanvasStatusIssue } from './CanvasStatusIssue'

/**
 * The nightly data check found events, properties, or tables the canvas declares but the project no
 * longer has. The check never repairs anything by itself: a person reads what moved and asks the
 * canvas's authoring agent for the fix from here.
 */
export function CanvasDataDriftNotice(): JSX.Element | null {
    const { dataDrift, liveBuild, canvas, fixRequestPending } = useValues(canvasSceneLogic)
    const { requestFix } = useActions(canvasSceneLogic)
    const { browseVersionId } = useValues(canvasHistoryLogic)

    if (!dataDrift || !canvas) {
        return null
    }
    const buildId = !browseVersionId ? (liveBuild?.id ?? null) : null
    const details = [
        ...dataDrift.missing.events.map((name) => `Event: ${name}`),
        ...dataDrift.missing.properties.map((property) => `${property.type} property: ${property.name}`),
        ...dataDrift.missing.tables.map((name) => `Table: ${name}`),
    ]

    return (
        <div className="flex items-center" data-attr="canvas-data-drift">
            <CanvasStatusIssue
                label="Data changed"
                title="Some data this canvas uses is gone"
                description="The nightly check found events, properties, or tables this canvas reads that this project no longer has. Parts of the canvas may show nothing until the agent that wrote it repoints them."
                details={details}
                dataAttr="canvas-data-drift-details"
                actions={
                    <Button
                        size="sm"
                        variant="primary"
                        loading={fixRequestPending}
                        disabled={!buildId}
                        onClick={() => buildId && requestFix({ buildId, errorType: DATA_DRIFT_ERROR_TYPE })}
                        data-attr="canvas-data-drift-ask-fix"
                    >
                        Ask agent to fix
                    </Button>
                }
            />
        </div>
    )
}
