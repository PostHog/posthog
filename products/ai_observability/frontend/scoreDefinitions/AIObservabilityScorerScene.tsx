import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonMenu, LemonTag } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getAccessControlDisabledReason, getProductAccessDisabledReason } from 'lib/utils/accessControlUtils'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { ScoreDefinitionForm } from './ScoreDefinitionForm'
import { formatKindLabel } from './scoreDefinitionModalUtils'
import { ScorerLogicProps, scorerLogic } from './scorerLogic'

export const scene: SceneExport<ScorerLogicProps> = {
    component: AIObservabilityScorerScene,
    logic: scorerLogic,
    productKey: ProductKey.AI_OBSERVABILITY,
    paramsToProps: ({ params, searchParams }) => ({
        scorerId: params.scorerId || 'new',
        duplicateFrom:
            params.scorerId === 'new' && typeof searchParams.duplicate === 'string'
                ? searchParams.duplicate
                : undefined,
    }),
}

export function AIObservabilityScorerScene(props: ScorerLogicProps): JSX.Element {
    const logic = scorerLogic(props)
    const { definition, definitionLoading, draft, isNew, hasChanges, willCreateVersion, saving, error, loadError } =
        useValues(logic)
    const {
        loadDefinition,
        save,
        createVersion,
        toggleArchive,
        setDraftField,
        updateOptionLabel,
        addOption,
        removeOption,
    } = useActions(logic)
    const { featureFlags } = useValues(featureFlagLogic)
    const editDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.LlmAnalytics,
        AccessControlLevel.Editor
    )
    const showHistory =
        !!featureFlags[FEATURE_FLAGS.AI_OBSERVABILITY_OFFLINE_EVALUATIONS] &&
        !getProductAccessDisabledReason({ sceneKey: Scene.AIObservabilityOfflineScorerHistory })

    if (definitionLoading || (!isNew && !definition && !loadError)) {
        return (
            <SceneContent>
                <LemonSkeleton className="h-8 w-64" />
                <LemonSkeleton className="h-96 w-full max-w-3xl" />
            </SceneContent>
        )
    }
    if (loadError) {
        return (
            <SceneContent>
                <LemonBanner type="error" action={{ children: 'Try again', onClick: loadDefinition }}>
                    {loadError}
                </LemonBanner>
                <LemonButton to={urls.aiObservabilityScorers()}>Back to scorers</LemonButton>
            </SceneContent>
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={isNew ? 'New scorer' : definition?.name || 'Scorer'}
                description="Define the scores used in manual reviews and offline evaluations."
                resourceType={{ type: 'llm_evaluations' }}
                actions={
                    <div className="flex flex-wrap items-center gap-2">
                        {!isNew && definition && (
                            <LemonMenu
                                items={[
                                    {
                                        label: 'Duplicate',
                                        to: urls.aiObservabilityScorer('new', { duplicate: definition.id }),
                                        disabledReason: editDisabledReason || (saving ? 'Saving scorer' : undefined),
                                        'data-attr': 'llma-scorer-duplicate',
                                    },
                                    {
                                        label: 'Create new version',
                                        disabledReason:
                                            editDisabledReason ||
                                            (saving
                                                ? 'Saving scorer'
                                                : hasChanges
                                                  ? 'Save your changes first'
                                                  : undefined),
                                        onClick: () =>
                                            LemonDialog.open({
                                                title: 'Create a new scorer version?',
                                                content: `Version ${definition.current_version + 1} will keep the current configuration. Use this when your external evaluator changes.`,
                                                primaryButton: { children: 'Create version', onClick: createVersion },
                                                secondaryButton: { children: 'Cancel' },
                                            }),
                                        'data-attr': 'llma-scorer-new-version',
                                    },
                                    {
                                        label: definition.archived ? 'Unarchive' : 'Archive',
                                        status: definition.archived ? 'default' : 'danger',
                                        disabledReason:
                                            editDisabledReason ||
                                            (saving
                                                ? 'Saving scorer'
                                                : hasChanges
                                                  ? 'Save your changes first'
                                                  : undefined),
                                        onClick: toggleArchive,
                                        'data-attr': 'llma-scorer-archive-toggle',
                                    },
                                ]}
                            >
                                <LemonButton icon={<IconEllipsis />} aria-label="Scorer actions" type="secondary" />
                            </LemonMenu>
                        )}
                        <LemonButton
                            to={urls.aiObservabilityScorers()}
                            type="secondary"
                            disabledReason={saving ? 'Saving scorer' : undefined}
                            data-attr="llma-scorer-cancel"
                        >
                            {hasChanges || isNew ? 'Cancel' : 'Back to scorers'}
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            form="scorer-form"
                            loading={saving}
                            disabledReason={editDisabledReason || (!hasChanges ? 'No unsaved changes' : undefined)}
                            data-attr="llma-scorer-save"
                        >
                            {isNew ? 'Create scorer' : 'Save changes'}
                        </LemonButton>
                    </div>
                }
            />
            <form
                id="scorer-form"
                className="max-w-3xl w-full space-y-6 pb-8"
                onSubmit={(event) => {
                    event.preventDefault()
                    save()
                }}
            >
                {!isNew && definition && (
                    <div className="flex flex-wrap gap-2 items-center justify-between border-b pb-4">
                        <div className="flex items-center flex-wrap gap-2">
                            <LemonTag>{formatKindLabel(definition.kind)}</LemonTag>
                            <span className="text-muted text-sm">{`Version ${definition.current_version}`}</span>
                            {definition.archived && <LemonTag type="muted">Archived</LemonTag>}
                            {definition.current_version_id && (
                                <CopyToClipboardInline
                                    explicitValue={definition.current_version_id}
                                    description="Scorer version ID"
                                >
                                    <span className="text-xs">Copy version ID</span>
                                </CopyToClipboardInline>
                            )}
                        </div>
                        {showHistory && (
                            <LemonButton
                                to={urls.aiObservabilityOfflineScorerHistory(definition.id)}
                                type="secondary"
                                size="small"
                                disabledReason={saving ? 'Saving scorer' : undefined}
                                data-attr="scorer-offline-history"
                            >
                                Offline evals history
                            </LemonButton>
                        )}
                    </div>
                )}
                {error && (
                    <LemonBanner
                        type="error"
                        action={
                            isNew
                                ? undefined
                                : {
                                      children: 'Reload scorer',
                                      onClick: () =>
                                          LemonDialog.open({
                                              title: 'Discard unsaved changes?',
                                              content: 'Reloading replaces this form with the latest saved scorer.',
                                              primaryButton: { children: 'Reload scorer', onClick: loadDefinition },
                                              secondaryButton: { children: 'Keep editing' },
                                          }),
                                  }
                        }
                    >
                        {error}
                    </LemonBanner>
                )}
                {willCreateVersion && definition && (
                    <LemonBanner type="info">
                        {`Saving these scoring rules creates version ${definition.current_version + 1}. Existing reviews and experiments keep their original configuration.`}
                    </LemonBanner>
                )}
                <ScoreDefinitionForm
                    draft={draft}
                    isNew={isNew}
                    disabled={saving || !!editDisabledReason}
                    setDraftField={setDraftField}
                    updateOptionLabel={updateOptionLabel}
                    addOption={addOption}
                    removeOption={removeOption}
                />
            </form>
        </SceneContent>
    )
}
