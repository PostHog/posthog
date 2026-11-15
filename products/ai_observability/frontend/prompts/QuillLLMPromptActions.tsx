import { useActions, useAsyncActions, useValues } from 'kea'

import { IconEllipsis, IconPencil, IconPlay } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { PromptMode, isPrompt, llmPromptLogic } from './llmPromptLogic'
import { openArchivePromptDialog, openDuplicatePromptDialog } from './utils'

export interface QuillLLMPromptActionsProps {
    openInPlaygroundUrl: string | undefined
}

export function QuillLLMPromptActions({ openInPlaygroundUrl }: QuillLLMPromptActionsProps): JSX.Element {
    const {
        isPromptFormSubmitting,
        isNewPrompt,
        isViewMode,
        prompt,
        isHistoricalVersion,
        nextVersion,
        isPromptFormDirty,
    } = useValues(llmPromptLogic)
    const { submitPromptForm, requestPublish, deletePrompt, setMode, setPromptFormValues, cancelEditing } =
        useActions(llmPromptLogic)
    const { duplicatePrompt } = useAsyncActions(llmPromptLogic)

    if (isViewMode) {
        return (
            <>
                {openInPlaygroundUrl ? (
                    <Button
                        variant="outline"
                        render={<LinkPrimitive to={openInPlaygroundUrl} />}
                        data-attr="llma-playground-open-from-prompt"
                    >
                        <IconPlay />
                        Open in Playground
                    </Button>
                ) : null}
                <AccessControlAction
                    resourceType={AccessControlResourceType.LlmAnalytics}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <Button
                        variant="primary"
                        onClick={() => {
                            if (isPrompt(prompt)) {
                                setPromptFormValues({ name: prompt.name, prompt: prompt.prompt })
                                setMode(PromptMode.Edit)
                            }
                        }}
                        tooltip={isHistoricalVersion ? 'Start a new version from this historical version' : undefined}
                        data-attr="llma-prompt-new-version-button"
                    >
                        <IconPencil />
                        New version
                    </Button>
                </AccessControlAction>
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={
                            <Button
                                variant="default"
                                size="icon"
                                aria-label="More"
                                tooltip="More"
                                data-attr="more-button"
                            />
                        }
                    >
                        <IconEllipsis />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                        <AccessControlAction
                            resourceType={AccessControlResourceType.LlmAnalytics}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <DropdownMenuItem
                                onClick={() => {
                                    if (isPrompt(prompt)) {
                                        const sourceName = prompt.name
                                        openDuplicatePromptDialog(sourceName, (newName) =>
                                            duplicatePrompt(sourceName, newName)
                                        )
                                    }
                                }}
                                data-attr="llma-prompt-detail-duplicate"
                            >
                                Duplicate
                            </DropdownMenuItem>
                        </AccessControlAction>
                        <AccessControlAction
                            resourceType={AccessControlResourceType.LlmAnalytics}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <DropdownMenuItem
                                variant="destructive"
                                onClick={() => openArchivePromptDialog(deletePrompt)}
                                data-attr="llma-prompt-delete-button"
                            >
                                Archive
                            </DropdownMenuItem>
                        </AccessControlAction>
                    </DropdownMenuContent>
                </DropdownMenu>
            </>
        )
    }

    return (
        <>
            {openInPlaygroundUrl ? (
                <Button
                    variant="outline"
                    render={<LinkPrimitive to={openInPlaygroundUrl} />}
                    disabledReason={
                        isPromptFormSubmitting
                            ? 'Saving…'
                            : isPromptFormDirty
                              ? 'You have unsaved edits — publish or cancel first'
                              : undefined
                    }
                    data-attr="llma-playground-open-from-prompt"
                >
                    <IconPlay />
                    Open in Playground
                </Button>
            ) : null}
            <Button
                variant="outline"
                onClick={() => cancelEditing()}
                disabledReason={isPromptFormSubmitting ? 'Saving…' : undefined}
                data-attr="llma-prompt-cancel-button"
            >
                Cancel
            </Button>
            <AccessControlAction
                resourceType={AccessControlResourceType.LlmAnalytics}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <Button
                    variant="primary"
                    onClick={isNewPrompt ? submitPromptForm : requestPublish}
                    loading={isPromptFormSubmitting}
                    disabledReason={
                        !isNewPrompt && !isHistoricalVersion && !isPromptFormDirty ? 'No changes to publish' : undefined
                    }
                    data-attr={isNewPrompt ? 'prompt-create-button' : 'prompt-save-button'}
                >
                    {isNewPrompt ? 'Create prompt' : nextVersion ? `Publish v${nextVersion}` : 'Publish version'}
                </Button>
            </AccessControlAction>
        </>
    )
}
