import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonButton, LemonInput, LemonTextArea } from '@posthog/lemon-ui'

import { wasNotebookNodeJustInserted } from 'lib/components/MarkdownNotebook/freshlyInserted'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { NotebookNodeAttributeProperties } from '../../types'
import { notebookNodeLogic } from '../notebookNodeLogic'
import { getGenUIFrameSchemas } from './genUIFrames'
import type { NotebookNodeGenUIAttributes } from './NotebookNodeGenUI'
import { notebookNodeGenUILogic } from './notebookNodeGenUILogic'

export function NotebookNodeGenUISettings({
    attributes,
    updateAttributes,
}: NotebookNodeAttributeProperties<NotebookNodeGenUIAttributes>): JSX.Element {
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const { isEditable, notebookLogic } = useValues(nodeLogic)
    const { content } = useValues(notebookLogic)
    const { schemas, missing } = getGenUIFrameSchemas(content, attributes.inputs ?? '')
    const logic = notebookNodeGenUILogic({
        id: attributes.id ?? '',
        nodeId: attributes.nodeId,
        channelId: attributes.channelId,
        prompt: attributes.prompt ?? '',
        frames: schemas,
        missingFrames: missing,
        isEditable,
        updateAttributes,
    })
    const { creatingCanvas, isGenerating } = useValues(logic)
    const { createFromPrompt } = useActions(logic)
    const mutationInFlight = creatingCanvas || isGenerating

    return (
        <div className="flex flex-col gap-3 p-3">
            <div>
                <LemonLabel>Prompt</LemonLabel>
                <LemonTextArea
                    value={attributes.prompt ?? ''}
                    onChange={(value) => updateAttributes({ prompt: value || undefined })}
                    placeholder="Describe the custom visualization you want to generate."
                    minRows={5}
                    autoFocus={wasNotebookNodeJustInserted(attributes.nodeId)}
                    disabled={!isEditable}
                />
            </div>
            <div>
                <LemonLabel>Dataframes</LemonLabel>
                <LemonInput
                    value={attributes.inputs ?? ''}
                    onChange={(value) => updateAttributes({ inputs: value })}
                    placeholder="pandas_df, another_df"
                    disabled={!isEditable}
                />
                <div className="mt-1 text-xs text-muted">
                    Enter up to four named outputs from SQL or Python cells. The visualization receives their saved
                    preview rows.
                </div>
            </div>
            <LemonButton
                type="primary"
                onClick={() => createFromPrompt()}
                loading={mutationInFlight}
                disabledReason={
                    mutationInFlight
                        ? 'Visualization generation is already running'
                        : !(attributes.prompt ?? '').trim()
                          ? 'Add a prompt first'
                          : undefined
                }
            >
                {attributes.id ? 'Regenerate visualization' : 'Generate visualization'}
            </LemonButton>
            {missing.length > 0 ? (
                <div className="text-xs text-warning-dark">
                    Run these dataframes before testing the visualization: {missing.join(', ')}
                </div>
            ) : null}
        </div>
    )
}
