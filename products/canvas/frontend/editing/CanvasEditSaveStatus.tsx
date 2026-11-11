import { useActions, useValues } from 'kea'

import { IconCheckCircle } from '@posthog/icons'
import { Button, Spinner, Text } from '@posthog/quill'

import { CanvasStatusIssue } from '../scene/CanvasStatusIssue'
import { canvasEditLogic } from './canvasEditLogic'

/**
 * Whether the author's edits are published yet, in the canvas header while editing. A failed save
 * or a newer version from somewhere else opens what went wrong and the ways out of it.
 */
export function CanvasEditSaveStatus(): JSX.Element | null {
    const { sourceEditing, entry, saveStatus } = useValues(canvasEditLogic)
    const { retrySave, resolveConflict, askAgent } = useActions(canvasEditLogic)

    if (!sourceEditing || !entry || !saveStatus) {
        return null
    }
    if (entry.conflict) {
        return (
            <div className="flex items-center" data-attr="canvas-save-status">
                <CanvasStatusIssue
                    label="Save conflict"
                    title="This canvas changed somewhere else"
                    description="A newer version was saved while you edited. Load it and drop your unsaved edits, or keep your edits and replace it."
                    details={[]}
                    dataAttr="canvas-save-conflict-details"
                    actions={
                        <>
                            <Button
                                size="sm"
                                variant="outline"
                                onClick={() => resolveConflict(false)}
                                data-attr="canvas-conflict-load-latest"
                            >
                                Load the latest
                            </Button>
                            <Button
                                size="sm"
                                variant="primary"
                                onClick={() => resolveConflict(true)}
                                data-attr="canvas-conflict-keep-mine"
                            >
                                Keep my edits
                            </Button>
                        </>
                    }
                />
            </div>
        )
    }
    if (entry.saveError) {
        const saveError = entry.saveError
        return (
            <div className="flex items-center" data-attr="canvas-save-status">
                <CanvasStatusIssue
                    label="Not saved"
                    title="Your changes are not saved"
                    description="Your last change didn't publish. Try again, or ask the agent to fix the source if the error points to it."
                    details={[saveError]}
                    dataAttr="canvas-save-error-details"
                    actions={
                        <>
                            <Button
                                size="sm"
                                variant="outline"
                                onClick={() => retrySave()}
                                data-attr="canvas-save-retry"
                            >
                                Try again
                            </Button>
                            <Button
                                size="sm"
                                variant="primary"
                                onClick={() =>
                                    askAgent(
                                        `Saving this canvas fails with: "${saveError}". Fix the canvas source so it passes validation.`
                                    )
                                }
                                data-attr="canvas-save-ask-agent"
                            >
                                Ask agent to fix
                            </Button>
                        </>
                    }
                />
            </div>
        )
    }
    const saving = saveStatus.saving || saveStatus.dirty
    return (
        <Text
            render={<span />}
            size="xs"
            variant="muted"
            className="flex items-center gap-1 px-1"
            aria-live="polite"
            data-attr="canvas-save-status"
        >
            {saving ? <Spinner aria-hidden="true" /> : <IconCheckCircle aria-hidden="true" />}
            <span>{saving ? 'Saving…' : 'Saved'}</span>
        </Text>
    )
}
