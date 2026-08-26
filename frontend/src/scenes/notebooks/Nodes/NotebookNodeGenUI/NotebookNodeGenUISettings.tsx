import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonCollapse, LemonModal, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { wasNotebookNodeJustInserted } from 'lib/components/MarkdownNotebook/freshlyInserted'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { CodeEditor } from 'lib/monaco/CodeEditor'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import { NotebookNodeAttributeProperties } from '../../types'
import { notebookNodeLogic } from '../notebookNodeLogic'
import { DEFAULT_GENUI_MODEL, GENUI_MODEL_OPTIONS } from './genUIModels'
import type { NotebookNodeGenUIAttributes } from './NotebookNodeGenUI'
import { formatGenUIElapsed, notebookNodeGenUILogic } from './notebookNodeGenUILogic'

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
    const {
        cancellationInFlight,
        elapsedSeconds,
        error,
        generationDraftModel,
        generationDraftPrompt,
        generationInFlight,
        generationModalOperation,
        isWorking,
        restoreInFlight,
        selectedVersion,
        selectedVersionId,
        sourceDraft,
        sourceError,
        sourceLoading,
        sourceModalOpen,
        sourceNote,
        sourceSaving,
        status,
        workingStatus,
    } = useValues(logic)
    const {
        cancelGeneration,
        closeGenerationModal,
        closeSourceEditor,
        generateVisualization,
        openGenerationModal,
        openSourceEditor,
        refreshData,
        restoreSelectedVersion,
        saveSource,
        selectVersion,
        setGenerationDraftModel,
        setGenerationDraftPrompt,
        setSourceDraft,
        setSourceNote,
    } = useActions(logic)
    const promptId = `genui-prompt-${attributes.nodeId}`
    const modelId = `genui-model-${attributes.nodeId}`
    const modalPromptId = `genui-change-prompt-${attributes.nodeId}`
    const modalModelId = `genui-change-model-${attributes.nodeId}`
    const sourceNoteId = `genui-source-note-${attributes.nodeId}`
    const hasVersions = Boolean(status?.versions.length)
    const isCurrentVersion = selectedVersionId === status?.current_version_id
    const initialPrompt = attributes.prompt ?? ''
    const modalTitle = generationModalOperation === 'improve' ? 'Improve visualization' : 'Regenerate visualization'
    const modalDescription =
        generationModalOperation === 'improve'
            ? 'Describe one change. The generator will update the current source and preserve everything else.'
            : 'Edit the complete prompt below. This creates a new visualization from scratch and keeps the existing versions.'
    const sourceIsEditable = isEditable && isCurrentVersion
    const submitGenerationDraft = (prompt: string): void => {
        if (!generationModalOperation || !prompt.trim() || generationInFlight) {
            return
        }
        generateVisualization(prompt, generationDraftModel, generationModalOperation)
    }

    return (
        <div className="flex flex-col gap-3 p-3">
            {!hasVersions ? (
                <>
                    <div>
                        <LemonLabel htmlFor={promptId}>Prompt</LemonLabel>
                        <LemonTextArea
                            id={promptId}
                            value={initialPrompt}
                            onChange={(value) => updateAttributes({ prompt: value || undefined })}
                            placeholder="Describe the visualization you want to generate."
                            minRows={5}
                            autoFocus={wasNotebookNodeJustInserted(attributes.nodeId)}
                            disabled={!isEditable || isWorking}
                            className="mt-1 ph-no-capture"
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
                            disabled={!isEditable || isWorking}
                            className="mt-1"
                            data-attr="genui-model-select"
                        />
                    </div>
                </>
            ) : (
                <>
                    <div>
                        <LemonLabel>Version history</LemonLabel>
                        <LemonSelect
                            value={selectedVersionId ?? undefined}
                            options={[...(status?.versions ?? [])].reverse().map((version) => ({
                                value: version.id,
                                label: `Version ${version.version}${
                                    version.id === status?.current_version_id ? ' (current)' : ''
                                } · ${humanFriendlyDetailedTime(version.created_at)}`,
                            }))}
                            onChange={selectVersion}
                            fullWidth
                            className="mt-1"
                            data-attr="genui-version-select"
                        />
                    </div>
                    {selectedVersion ? (
                        <div className="rounded border bg-surface-primary p-3">
                            {selectedVersion.operation === 'improve' && selectedVersion.prompt ? (
                                <div className="mb-3">
                                    <div className="mb-1 text-xs font-semibold text-secondary">Change made</div>
                                    <div className="ph-no-capture whitespace-pre-wrap text-sm">
                                        {selectedVersion.prompt}
                                    </div>
                                </div>
                            ) : null}
                            <LemonCollapse
                                embedded
                                size="small"
                                panels={[
                                    {
                                        key: 'prompt',
                                        header: 'Prompt for this version',
                                        content: (
                                            <div className="ph-no-capture max-h-48 overflow-auto whitespace-pre-wrap text-sm text-secondary">
                                                {selectedVersion.effective_prompt ||
                                                    'No prompt was recorded for this version.'}
                                            </div>
                                        ),
                                    },
                                ]}
                            />
                        </div>
                    ) : null}
                </>
            )}

            <div className="flex flex-wrap items-start gap-2">
                {isWorking && workingStatus ? (
                    <>
                        <div className="flex min-w-0 flex-1 flex-col gap-1" role="status" aria-live="polite">
                            <div className="flex flex-wrap items-center gap-2 text-sm text-secondary">
                                <Spinner />
                                <span>{workingStatus.label}</span>
                                <span className="font-mono tabular-nums" data-attr="genui-elapsed-time">
                                    Elapsed {formatGenUIElapsed(elapsedSeconds)}
                                </span>
                            </div>
                            <span className="text-xs text-muted">{workingStatus.detail}</span>
                            <span
                                className={workingStatus.isOverEstimate ? 'text-xs text-warning' : 'text-xs text-muted'}
                            >
                                {workingStatus.timing}
                            </span>
                        </div>
                        {status?.generation_id || generationInFlight ? (
                            <LemonButton onClick={cancelGeneration} loading={cancellationInFlight}>
                                Cancel
                            </LemonButton>
                        ) : null}
                    </>
                ) : hasVersions ? (
                    <>
                        {!isCurrentVersion && isEditable ? (
                            <LemonButton onClick={restoreSelectedVersion} loading={restoreInFlight}>
                                Restore this version
                            </LemonButton>
                        ) : null}
                        {isCurrentVersion && isEditable ? (
                            <LemonButton type="primary" onClick={() => openGenerationModal('improve')}>
                                Improve...
                            </LemonButton>
                        ) : null}
                        {isEditable ? (
                            <LemonButton onClick={() => openGenerationModal('regenerate')}>Regenerate</LemonButton>
                        ) : null}
                        <LemonButton onClick={openSourceEditor}>
                            {sourceIsEditable ? 'View or edit source' : 'View source'}
                        </LemonButton>
                        <LemonButton onClick={refreshData} data-attr="genui-reload-data">
                            Reload data
                        </LemonButton>
                    </>
                ) : (
                    <LemonButton
                        type="primary"
                        onClick={() =>
                            generateVisualization(initialPrompt, attributes.model ?? DEFAULT_GENUI_MODEL, 'initial')
                        }
                        disabledReason={!initialPrompt.trim() ? 'Add a prompt first' : undefined}
                        loading={generationInFlight}
                    >
                        Generate visualization
                    </LemonButton>
                )}
            </div>
            {error || status?.error_detail ? (
                <div className="text-xs text-danger">{error || status?.error_detail}</div>
            ) : null}

            <LemonModal
                isOpen={generationModalOperation !== null}
                onClose={closeGenerationModal}
                title={modalTitle}
                description={modalDescription}
                width={640}
                footer={
                    <>
                        <LemonButton onClick={closeGenerationModal}>Cancel</LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={() => submitGenerationDraft(generationDraftPrompt)}
                            disabledReason={!generationDraftPrompt.trim() ? 'Add instructions first' : undefined}
                            loading={generationInFlight}
                        >
                            {generationModalOperation === 'improve' ? 'Improve' : 'Regenerate'}
                        </LemonButton>
                    </>
                }
            >
                <div className="flex flex-col gap-4">
                    <div>
                        <LemonLabel htmlFor={modalPromptId}>
                            {generationModalOperation === 'improve' ? 'Change to make' : 'Full prompt'}
                        </LemonLabel>
                        <LemonTextArea
                            id={modalPromptId}
                            value={generationDraftPrompt}
                            onChange={setGenerationDraftPrompt}
                            onPressCmdEnter={submitGenerationDraft}
                            minRows={6}
                            autoFocus
                            className="mt-1 ph-no-capture"
                            placeholder={
                                generationModalOperation === 'improve'
                                    ? 'For example, make the colors lighter and increase the label contrast.'
                                    : 'Describe the complete visualization.'
                            }
                        />
                    </div>
                    <div>
                        <LemonLabel htmlFor={modalModelId}>Model</LemonLabel>
                        <LemonSelect
                            id={modalModelId}
                            value={generationDraftModel}
                            options={GENUI_MODEL_OPTIONS}
                            onChange={setGenerationDraftModel}
                            fullWidth
                            className="mt-1"
                        />
                    </div>
                </div>
            </LemonModal>

            <LemonModal
                isOpen={sourceModalOpen}
                onClose={closeSourceEditor}
                title={sourceIsEditable ? 'View or edit source' : 'View source'}
                description={
                    sourceIsEditable
                        ? 'Saving source creates a new version. The previous source remains in history.'
                        : 'Restore this version before editing its source.'
                }
                width={960}
                footer={
                    <>
                        <LemonButton onClick={closeSourceEditor}>Close</LemonButton>
                        {sourceIsEditable ? (
                            <LemonButton
                                type="primary"
                                onClick={saveSource}
                                loading={sourceSaving}
                                disabledReason={
                                    !sourceDraft.trim()
                                        ? 'Source cannot be empty'
                                        : !sourceNote.trim()
                                          ? 'Describe your change first'
                                          : undefined
                                }
                            >
                                Save as new version
                            </LemonButton>
                        ) : null}
                    </>
                }
            >
                <div className="flex flex-col gap-3">
                    {sourceError ? <LemonBanner type="error">{sourceError}</LemonBanner> : null}
                    {sourceLoading ? (
                        <div className="flex h-80 items-center justify-center">
                            <Spinner />
                        </div>
                    ) : (
                        <CodeEditor
                            className="ph-no-capture rounded border"
                            language="typescript"
                            value={sourceDraft}
                            onChange={(value) => setSourceDraft(value ?? '')}
                            height="55vh"
                            path={`notebook-genui/${attributes.nodeId}/${selectedVersionId ?? 'current'}.tsx`}
                            options={{ readOnly: !sourceIsEditable, minimap: { enabled: false } }}
                        />
                    )}
                    {sourceIsEditable && !sourceLoading ? (
                        <div>
                            <LemonLabel htmlFor={sourceNoteId}>Change description</LemonLabel>
                            <LemonTextArea
                                id={sourceNoteId}
                                value={sourceNote}
                                onChange={setSourceNote}
                                placeholder="Describe what you changed."
                                minRows={2}
                                className="mt-1 ph-no-capture"
                            />
                        </div>
                    ) : null}
                </div>
            </LemonModal>
        </div>
    )
}
