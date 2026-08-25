import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonButton, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { wasNotebookNodeJustInserted } from 'lib/components/MarkdownNotebook/freshlyInserted'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { NotebookNodeAttributeProperties } from '../../types'
import { notebookNodeLogic } from '../notebookNodeLogic'
import { confirmGenUIGeneration } from './confirmGenUIGeneration'
import { DEFAULT_GENUI_MODEL, GENUI_MODEL_OPTIONS } from './genUIModels'
import type { NotebookNodeGenUIAttributes } from './NotebookNodeGenUI'
import { notebookNodeGenUILogic } from './notebookNodeGenUILogic'

export function NotebookNodeGenUISettings({
    attributes,
    updateAttributes,
}: NotebookNodeAttributeProperties<NotebookNodeGenUIAttributes>): JSX.Element {
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const { isEditable, notebookLogic } = useValues(nodeLogic)
    const logic = notebookNodeGenUILogic({
        notebookShortId: notebookLogic.props.shortId,
        nodeId: attributes.nodeId,
        prompt: attributes.prompt ?? '',
        model: attributes.model ?? DEFAULT_GENUI_MODEL,
        isEditable,
        persistNotebook: async (): Promise<void> => {
            await notebookLogic.asyncActions.saveNotebook({
                content: notebookLogic.values.content,
                title: notebookLogic.values.title,
            })
        },
    })
    const { cancellationInFlight, error, generationInFlight, status } = useValues(logic)
    const { cancelGeneration, generateVisualization, refreshData } = useActions(logic)
    const promptId = `genui-prompt-${attributes.nodeId}`
    const modelId = `genui-model-${attributes.nodeId}`
    const isBuilding = status?.lifecycle_status === 'building'
    const isWorking = generationInFlight || isBuilding
    const workingLabel = generationInFlight
        ? status?.lifecycle_status === 'ready'
            ? 'Regenerating visualization…'
            : 'Generating visualization…'
        : 'Building visualization…'
    const disabledReason = !(attributes.prompt ?? '').trim() ? 'Add a prompt first' : undefined

    const generate = (): void => {
        if (status?.lifecycle_status === 'ready' || status?.lifecycle_status === 'failed') {
            confirmGenUIGeneration(generateVisualization)
        } else {
            generateVisualization()
        }
    }

    return (
        <div className="flex flex-col gap-3 p-3">
            <div>
                <LemonLabel htmlFor={promptId}>Prompt</LemonLabel>
                <LemonTextArea
                    id={promptId}
                    value={attributes.prompt ?? ''}
                    onChange={(value) => updateAttributes({ prompt: value || undefined })}
                    placeholder="Describe the visualization you want to generate."
                    minRows={5}
                    autoFocus={wasNotebookNodeJustInserted(attributes.nodeId)}
                    disabled={!isEditable}
                    className="mt-1"
                />
            </div>
            <div className="text-xs text-muted">
                Results from SQL and Python cells in this notebook are included automatically.
            </div>
            <div>
                <LemonLabel htmlFor={modelId}>Model</LemonLabel>
                <LemonSelect
                    id={modelId}
                    value={attributes.model ?? DEFAULT_GENUI_MODEL}
                    options={GENUI_MODEL_OPTIONS}
                    onChange={(model) => updateAttributes({ model })}
                    fullWidth
                    disabled={!isEditable}
                    className="mt-1"
                    // pinned: this selector is part of the browser automation contract
                    data-attr="genui-model-select"
                />
            </div>
            <div className="flex flex-wrap items-center gap-2">
                {isWorking ? (
                    <>
                        <div
                            className="flex items-center gap-2 text-sm text-secondary"
                            role="status"
                            aria-live="polite"
                        >
                            <Spinner />
                            <span>{workingLabel}</span>
                        </div>
                        {generationInFlight ? (
                            <LemonButton onClick={cancelGeneration} loading={cancellationInFlight}>
                                Cancel
                            </LemonButton>
                        ) : null}
                    </>
                ) : (
                    <>
                        {status?.lifecycle_status === 'ready' ? (
                            <LemonButton type="primary" onClick={refreshData}>
                                Reload data
                            </LemonButton>
                        ) : null}
                        <LemonButton
                            type={status?.lifecycle_status === 'ready' ? 'secondary' : 'primary'}
                            onClick={generate}
                            disabledReason={disabledReason}
                        >
                            {status?.lifecycle_status === 'ready' ? 'Regenerate' : 'Generate visualization'}
                        </LemonButton>
                    </>
                )}
            </div>
            {error ? <div className="text-xs text-danger">{error}</div> : null}
        </div>
    )
}
