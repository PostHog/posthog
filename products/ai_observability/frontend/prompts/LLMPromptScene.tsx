import { useActions, useAsyncActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { combineUrl, router } from 'kea-router'

import { IconPencil, IconPlay } from '@posthog/icons'
import { LemonButton, LemonTabs } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { NotFound } from 'lib/components/NotFound'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { PromptLogicProps, PromptMode, isPrompt, llmPromptLogic } from './llmPromptLogic'
import {
    PromptEditForm,
    PromptExperiments,
    PromptRelatedTraces,
    PromptUsage,
    PromptVersionSidebar,
    PromptViewDetails,
    PublishReviewModal,
    cleanPromptSearchParams,
} from './promptSceneComponents'
import { openArchivePromptDialog, openDuplicatePromptDialog } from './utils'

export const scene: SceneExport<PromptLogicProps> = {
    component: LLMPromptScene,
    logic: llmPromptLogic,
    productKey: ProductKey.AI_OBSERVABILITY,
    paramsToProps: ({ params: { name }, searchParams }) => ({
        promptName: name && name !== 'new' ? name : 'new',
        // kea-router JSON-decodes query values, so ?edit=true arrives as boolean true
        mode: String(searchParams?.edit) === 'true' ? PromptMode.Edit : PromptMode.View,
        selectedVersion: searchParams?.version ? Number(searchParams.version) || null : null,
    }),
}

export function LLMPromptScene(): JSX.Element {
    const {
        shouldDisplaySkeleton,
        promptLoading,
        versionsLoading,
        isPromptFormSubmitting,
        isPromptMissing,
        isNewPrompt,
        promptForm,
        isViewMode,
        prompt,
        isHistoricalVersion,
        versions,
        canLoadMoreVersions,
        nextVersion,
        isPromptFormDirty,
    } = useValues(llmPromptLogic)
    const { searchParams } = useValues(router)
    const currentSearchParams = searchParams ?? {}
    const activeViewTab =
        searchParams?.tab === 'usage' ? 'usage' : searchParams?.tab === 'experiments' ? 'experiments' : 'overview'

    const {
        submitPromptForm,
        requestPublish,
        deletePrompt,
        setMode,
        setPromptFormValues,
        loadMoreVersions,
        cancelEditing,
    } = useActions(llmPromptLogic)
    const { duplicatePrompt } = useAsyncActions(llmPromptLogic)
    const sourcePromptName = !isNewPrompt && prompt && isPrompt(prompt) ? prompt.name : null
    const sourcePromptVersion = isHistoricalVersion && isPrompt(prompt) ? prompt.version : null
    const openInPlaygroundUrl = sourcePromptName
        ? combineUrl(urls.aiObservabilityPlayground(), {
              source_prompt_name: sourcePromptName,
              ...(sourcePromptVersion ? { source_prompt_version: sourcePromptVersion } : {}),
          }).url
        : undefined

    if (isPromptMissing) {
        return <NotFound object="prompt" />
    }

    if (shouldDisplaySkeleton) {
        return (
            <div className="flex flex-col gap-2">
                <LemonSkeleton active className="h-4 w-2/5" />
                <LemonSkeleton active className="h-4 w-full" />
                <LemonSkeleton active className="h-4 w-3/5" />
            </div>
        )
    }

    const content = isViewMode ? (
        <SceneContent>
            <SceneTitleSection
                name={prompt && 'name' in prompt ? prompt.name : 'Prompt'}
                resourceType={{ type: 'llm_analytics' }}
                isLoading={promptLoading}
                actions={
                    <>
                        {openInPlaygroundUrl ? (
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconPlay />}
                                to={openInPlaygroundUrl}
                                data-attr="llma-playground-open-from-prompt"
                            >
                                Open in Playground
                            </LemonButton>
                        ) : null}
                        <AccessControlAction
                            resourceType={AccessControlResourceType.LlmAnalytics}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <LemonButton
                                type="primary"
                                icon={<IconPencil />}
                                onClick={() => {
                                    if (isPrompt(prompt)) {
                                        setPromptFormValues({ name: prompt.name, prompt: prompt.prompt })
                                        setMode(PromptMode.Edit)
                                    }
                                }}
                                size="small"
                                tooltip={
                                    isHistoricalVersion ? 'Start a new version from this historical version' : undefined
                                }
                                data-attr="llma-prompt-new-version-button"
                            >
                                New version
                            </LemonButton>
                        </AccessControlAction>

                        <More
                            size="small"
                            overlay={
                                <>
                                    <AccessControlAction
                                        resourceType={AccessControlResourceType.LlmAnalytics}
                                        minAccessLevel={AccessControlLevel.Editor}
                                    >
                                        <LemonButton
                                            onClick={() => {
                                                if (isPrompt(prompt)) {
                                                    const sourceName = prompt.name
                                                    openDuplicatePromptDialog(sourceName, (newName) =>
                                                        duplicatePrompt(sourceName, newName)
                                                    )
                                                }
                                            }}
                                            data-attr="llma-prompt-detail-duplicate"
                                            fullWidth
                                        >
                                            Duplicate
                                        </LemonButton>
                                    </AccessControlAction>

                                    <AccessControlAction
                                        resourceType={AccessControlResourceType.LlmAnalytics}
                                        minAccessLevel={AccessControlLevel.Editor}
                                    >
                                        <LemonButton
                                            status="danger"
                                            onClick={() => openArchivePromptDialog(deletePrompt)}
                                            data-attr="llma-prompt-delete-button"
                                            fullWidth
                                        >
                                            Archive
                                        </LemonButton>
                                    </AccessControlAction>
                                </>
                            }
                        />
                    </>
                }
            />

            <div className="flex flex-col gap-6 xl:flex-row">
                <div className="min-w-0 flex-1">
                    {prompt && isPrompt(prompt) ? (
                        <LemonTabs
                            activeKey={activeViewTab}
                            onChange={(tab) =>
                                router.actions.replace(urls.aiObservabilityPrompt(prompt.name), {
                                    ...cleanPromptSearchParams(
                                        currentSearchParams,
                                        prompt.is_latest ? null : prompt.version
                                    ),
                                    tab,
                                })
                            }
                            tabs={[
                                {
                                    key: 'overview',
                                    label: 'Overview',
                                    content: (
                                        <>
                                            <PromptViewDetails />
                                            <PromptRelatedTraces />
                                        </>
                                    ),
                                },
                                {
                                    key: 'usage',
                                    label: 'Usage',
                                    content: <PromptUsage prompt={prompt} />,
                                },
                                {
                                    key: 'experiments',
                                    label: 'Experiments',
                                    content: <PromptExperiments prompt={prompt} />,
                                },
                            ]}
                        />
                    ) : (
                        <>
                            <PromptViewDetails />
                            <PromptRelatedTraces />
                        </>
                    )}
                </div>

                {!isNewPrompt && (
                    <PromptVersionSidebar
                        promptName={isPrompt(prompt) ? prompt.name : ''}
                        prompt={isPrompt(prompt) ? prompt : null}
                        versions={versions}
                        versionsLoading={versionsLoading}
                        canLoadMoreVersions={canLoadMoreVersions}
                        loadMoreVersions={loadMoreVersions}
                        searchParams={currentSearchParams}
                    />
                )}
            </div>
        </SceneContent>
    ) : (
        <Form id="prompt-form" formKey="promptForm" logic={llmPromptLogic}>
            <SceneContent>
                <SceneTitleSection
                    name={promptForm.name || 'New prompt'}
                    resourceType={{ type: 'llm_analytics' }}
                    isLoading={promptLoading}
                    actions={
                        <>
                            {openInPlaygroundUrl ? (
                                <LemonButton
                                    type="secondary"
                                    icon={<IconPlay />}
                                    to={openInPlaygroundUrl}
                                    disabledReason={
                                        isPromptFormSubmitting
                                            ? 'Saving…'
                                            : isPromptFormDirty
                                              ? 'You have unsaved edits — publish or cancel first'
                                              : undefined
                                    }
                                    size="small"
                                    data-attr="llma-playground-open-from-prompt"
                                >
                                    Open in Playground
                                </LemonButton>
                            ) : null}
                            <LemonButton
                                type="secondary"
                                onClick={() => cancelEditing()}
                                disabledReason={isPromptFormSubmitting ? 'Saving…' : undefined}
                                size="small"
                                data-attr="llma-prompt-cancel-button"
                            >
                                Cancel
                            </LemonButton>

                            <AccessControlAction
                                resourceType={AccessControlResourceType.LlmAnalytics}
                                minAccessLevel={AccessControlLevel.Editor}
                            >
                                <LemonButton
                                    type="primary"
                                    onClick={isNewPrompt ? submitPromptForm : requestPublish}
                                    loading={isPromptFormSubmitting}
                                    disabledReason={
                                        !isNewPrompt && !isHistoricalVersion && !isPromptFormDirty
                                            ? 'No changes to publish'
                                            : undefined
                                    }
                                    size="small"
                                    data-attr={isNewPrompt ? 'prompt-create-button' : 'prompt-save-button'}
                                >
                                    {isNewPrompt
                                        ? 'Create prompt'
                                        : nextVersion
                                          ? `Publish v${nextVersion}`
                                          : 'Publish version'}
                                </LemonButton>
                            </AccessControlAction>
                        </>
                    }
                />

                <div className="flex flex-col gap-6 xl:flex-row">
                    <div className="min-w-0 flex-1">
                        <PromptEditForm
                            isHistoricalVersion={isHistoricalVersion}
                            selectedVersion={isPrompt(prompt) ? prompt.version : null}
                        />
                        <PublishReviewModal />
                    </div>

                    {!isNewPrompt && (
                        <PromptVersionSidebar
                            promptName={isPrompt(prompt) ? prompt.name : ''}
                            prompt={isPrompt(prompt) ? prompt : null}
                            versions={versions}
                            versionsLoading={versionsLoading}
                            canLoadMoreVersions={canLoadMoreVersions}
                            loadMoreVersions={loadMoreVersions}
                            searchParams={currentSearchParams}
                            readOnly
                        />
                    )}
                </div>
            </SceneContent>
        </Form>
    )
    return content
}
