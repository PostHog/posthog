import { useActions, useAsyncActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconArchive, IconCopy, IconPencil, IconPlay, IconUpload, IconX } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { PromptMode, isPrompt, llmPromptLogic } from './llmPromptLogic'
import { QuillPromptPublishButton } from './QuillPromptPublishButton'
import { openArchivePromptDialog, openDuplicatePromptDialog } from './utils'

const RESOURCE_TYPE = 'llm-prompt'
const SAVING_REASON = 'Saving…'

interface LLMPromptSceneMenuBarProps {
    openInPlaygroundUrl: string | undefined
}

export function LLMPromptSceneMenuBar(props: LLMPromptSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <LLMPromptSceneMenuBarInner {...props} /> : null
}

function LLMPromptSceneMenuBarInner({ openInPlaygroundUrl }: LLMPromptSceneMenuBarProps): JSX.Element {
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
    const accessDisabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.LlmAnalytics, AccessControlLevel.Editor) ?? undefined

    const openInPlayground: SceneAction[] = openInPlaygroundUrl
        ? [
              {
                  group: 'view',
                  id: `${RESOURCE_TYPE}-menubar-open-in-playground`,
                  label: 'Open in Playground',
                  icon: <IconPlay />,
                  disabledReason: isViewMode
                      ? undefined
                      : isPromptFormSubmitting
                        ? SAVING_REASON
                        : isPromptFormDirty
                          ? 'You have unsaved edits. Publish or cancel first'
                          : undefined,
                  onSelect: () => router.actions.push(openInPlaygroundUrl),
                  pinned: { order: 1, variant: 'secondary', dataAttr: 'llma-playground-open-from-prompt' },
              },
          ]
        : []

    const actions: SceneAction[] = isViewMode
        ? [
              {
                  group: 'edit',
                  section: 'version',
                  id: `${RESOURCE_TYPE}-menubar-new-version`,
                  label: 'New version',
                  icon: <IconPencil />,
                  tooltip: isHistoricalVersion ? 'Start a new version from this historical version' : undefined,
                  disabledReason: accessDisabledReason,
                  onSelect: () => {
                      if (isPrompt(prompt)) {
                          setPromptFormValues({ name: prompt.name, prompt: prompt.prompt })
                          setMode(PromptMode.Edit)
                      }
                  },
                  pinned: { order: 3, variant: 'primary', dataAttr: 'llma-prompt-new-version-button' },
              },
              {
                  group: 'edit',
                  // pinned: data-attr values are wire strings
                  id: 'llma-prompt-detail-duplicate',
                  label: 'Duplicate',
                  icon: <IconCopy />,
                  opensFloatingUi: true,
                  disabledReason: accessDisabledReason,
                  onSelect: () => {
                      if (isPrompt(prompt)) {
                          const sourceName = prompt.name
                          openDuplicatePromptDialog(sourceName, (newName) => duplicatePrompt(sourceName, newName))
                      }
                  },
              },
              ...openInPlayground,
              {
                  group: 'file',
                  section: 'delete',
                  id: 'llma-prompt-delete-button',
                  label: 'Archive',
                  icon: <IconArchive />,
                  destructive: true,
                  disabledReason: accessDisabledReason,
                  onSelect: () => openArchivePromptDialog(deletePrompt),
              },
          ]
        : [
              {
                  group: 'edit',
                  section: 'save',
                  id: `${RESOURCE_TYPE}-menubar-publish`,
                  label: isNewPrompt ? 'Create prompt' : nextVersion ? `Publish v${nextVersion}` : 'Publish version',
                  icon: <IconUpload />,
                  disabledReason:
                      accessDisabledReason ??
                      (isPromptFormSubmitting
                          ? SAVING_REASON
                          : !isNewPrompt && !isHistoricalVersion && !isPromptFormDirty
                            ? 'No changes to publish'
                            : undefined),
                  onSelect: isNewPrompt ? submitPromptForm : requestPublish,
                  pinned: {
                      order: 3,
                      variant: 'primary',
                      dataAttr: isNewPrompt ? 'prompt-create-button' : 'prompt-save-button',
                      render: () => <QuillPromptPublishButton />,
                  },
              },
              {
                  group: 'edit',
                  section: 'save',
                  id: `${RESOURCE_TYPE}-menubar-cancel`,
                  label: 'Cancel',
                  icon: <IconX />,
                  disabledReason: isPromptFormSubmitting ? SAVING_REASON : undefined,
                  onSelect: () => cancelEditing(),
                  pinned: { order: 2, variant: 'secondary', dataAttr: 'llma-prompt-cancel-button' },
              },
              ...openInPlayground,
          ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
