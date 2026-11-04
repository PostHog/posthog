import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconArrowLeft, IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonModal, Link } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { providerKeyStateLabel, providerLabel } from '../settings/providerKeyStateUtils'
import { EvaluationsTabs } from './EvaluationsTabs'
import { EvaluationTemplatesEmptyState } from './EvaluationTemplates'
import { llmEvaluationsLogic } from './llmEvaluationsLogic'
import { EvaluationResultsTable } from './overview/EvaluationResultsTable'
import { EvaluationsOverview } from './overview/EvaluationsOverview'

function AIObservabilityEvaluationsContent(): JSX.Element {
    const evaluationsLogic = llmEvaluationsLogic()
    const {
        evaluations,
        evaluationsLoading,
        evaluationsLoadFailed,
        unhealthyProviderKeysUsedByEvaluations,
        evaluationDirectories,
        evaluationDirectoriesLoading,
        selectedDirectory,
        directoryEditor,
        submitDirectoryLoading,
    } = useValues(evaluationsLogic)
    const { closeDirectoryEditor, setDirectoryEditorName, submitDirectory, selectDirectory } =
        useActions(evaluationsLogic)
    const { searchParams } = useValues(router)
    const settingsUrl = urls.settings('project-ai-observability', 'ai-observability-byok')

    // A failed list is not an empty project. The overview still loads, and in a directory it shows a retry.
    const showEmptyState =
        !evaluationsLoadFailed &&
        !evaluationsLoading &&
        !evaluationDirectoriesLoading &&
        evaluations.length === 0 &&
        evaluationDirectories.length === 0

    return (
        <div className="space-y-4">
            {!showEmptyState && unhealthyProviderKeysUsedByEvaluations.length > 0 && (
                <LemonBanner type="warning">
                    <div className="space-y-2">
                        <p>Some evaluations are using API keys that need attention.</p>
                        <ul className="list-disc pl-5 space-y-1">
                            {unhealthyProviderKeysUsedByEvaluations.map((providerKey) => (
                                <li key={providerKey.id}>
                                    <span className="font-semibold">{providerKey.name}</span> (
                                    {providerLabel(providerKey.provider)}) - {providerKeyStateLabel(providerKey.state)}:{' '}
                                    {providerKey.error_message || 'Unknown error'}
                                </li>
                            ))}
                        </ul>
                        <Link to={settingsUrl}>Go to settings to fix API keys.</Link>
                    </div>
                </LemonBanner>
            )}

            <div className={showEmptyState ? 'hidden' : 'flex flex-wrap justify-between items-start gap-3'}>
                <div className="min-w-0 flex-1 basis-64">
                    {selectedDirectory ? (
                        <div className="flex flex-wrap items-center gap-2">
                            <LemonButton
                                type="tertiary"
                                size="small"
                                icon={<IconArrowLeft />}
                                onClick={() => selectDirectory(null)}
                            >
                                Online evals
                            </LemonButton>
                            <span className="text-muted">/</span>
                            <h2 className="text-xl font-semibold m-0 break-words min-w-0">{selectedDirectory.name}</h2>
                        </div>
                    ) : (
                        <h2 className="text-xl font-semibold">Online evals</h2>
                    )}
                    <p className="text-muted">
                        Configure evaluation prompts and triggers to automatically assess your AI generations. Each
                        evaluation run is billed as an AI observability event.
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <AccessControlAction
                        resourceType={AccessControlResourceType.Evaluation}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            type="primary"
                            icon={<IconPlus />}
                            to={combineUrl(urls.aiObservabilityEvaluationTemplates(), searchParams).url}
                            data-attr="create-evaluation-button"
                            tooltip="Create evaluation"
                        >
                            Create evaluation
                        </LemonButton>
                    </AccessControlAction>
                </div>
            </div>

            {showEmptyState ? (
                <EvaluationTemplatesEmptyState />
            ) : (
                <>
                    <EvaluationsOverview />
                    <EvaluationResultsTable />
                </>
            )}

            <LemonModal
                isOpen={!!directoryEditor}
                onClose={closeDirectoryEditor}
                title={directoryEditor?.mode === 'rename' ? 'Rename directory' : 'New directory'}
                width={480}
                footer={
                    <>
                        <LemonButton type="secondary" onClick={closeDirectoryEditor} disabled={submitDirectoryLoading}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={() => submitDirectory()}
                            loading={submitDirectoryLoading}
                            disabledReason={!directoryEditor?.name.trim() ? 'Directory name is required' : undefined}
                            data-attr="save-evaluation-directory"
                        >
                            {directoryEditor?.mode === 'rename' ? 'Save directory' : 'Create directory'}
                        </LemonButton>
                    </>
                }
            >
                <LemonInput
                    value={directoryEditor?.name || ''}
                    onChange={(value) => setDirectoryEditorName(String(value || ''))}
                    placeholder="Directory name"
                    autoFocus
                    fullWidth
                    data-attr="evaluation-directory-name-input"
                />
            </LemonModal>
        </div>
    )
}

export function AIObservabilityEvaluationsScene(): JSX.Element {
    useMountedLogic(llmEvaluationsLogic())
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    return (
        <BindLogic logic={llmEvaluationsLogic} props={{}}>
            <SceneContent>
                <SceneTitleSection
                    name="Evaluations"
                    description="Configure and monitor automated LLM output evaluations."
                    resourceType={{
                        type: 'llm_evaluations',
                    }}
                    actions={
                        todayRailNav ? (
                            <Button
                                variant="outline"
                                render={
                                    <LinkPrimitive to="https://posthog.com/docs/ai-evals/evaluations" target="_blank" />
                                }
                            >
                                Documentation
                            </Button>
                        ) : (
                            <LemonButton
                                to="https://posthog.com/docs/ai-evals/evaluations"
                                type="secondary"
                                targetBlank
                                size="small"
                            >
                                Documentation
                            </LemonButton>
                        )
                    }
                />
                <EvaluationsTabs activeTab="online-evals">
                    <AIObservabilityEvaluationsContent />
                </EvaluationsTabs>
            </SceneContent>
        </BindLogic>
    )
}
