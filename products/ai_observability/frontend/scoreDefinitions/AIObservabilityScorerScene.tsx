import { useActions, useValues } from 'kea'

import { IconArrowLeft, IconEllipsis } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonMenu, LemonTag } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getAccessControlDisabledReason, getProductAccessDisabledReason } from 'lib/utils/accessControlUtils'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { openCreateScorerVersionDialog } from './openCreateScorerVersionDialog'
import { QuillAIObservabilityScorerActions } from './QuillAIObservabilityScorerActions'
import { ScoreDefinitionForm } from './ScoreDefinitionForm'
import { formatKindLabel } from './scoreDefinitionModalUtils'
import { ScorerLogicProps, scorerLogic } from './scorerLogic'
import { ScorersScene } from './ScorersScene'

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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const editDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.LlmAnalytics,
        AccessControlLevel.Editor
    )
    const showHistory =
        !!featureFlags[FEATURE_FLAGS.AI_OBSERVABILITY_OFFLINE_EVALUATIONS] &&
        !getProductAccessDisabledReason({ sceneKey: Scene.AIObservabilityOfflineScorerHistory })

    if (definitionLoading || (!isNew && !definition && !loadError)) {
        return (
            <ScorersScene>
                <LemonSkeleton className="h-8 w-64" />
                <LemonSkeleton className="h-96 w-full max-w-3xl" />
            </ScorersScene>
        )
    }
    if (loadError) {
        return (
            <ScorersScene>
                <LemonBanner type="error" action={{ children: 'Try again', onClick: loadDefinition }}>
                    {loadError}
                </LemonBanner>
                <LemonButton to={urls.aiObservabilityScorers()}>Back to scorers</LemonButton>
            </ScorersScene>
        )
    }

    return (
        <ScorersScene>
            <div className="flex flex-wrap items-center gap-3">
                <nav aria-label="Scorer" className="flex min-w-0 flex-1 basis-40 items-center gap-2">
                    <LemonButton
                        size="small"
                        icon={<IconArrowLeft />}
                        aria-label="Back to scorers"
                        tooltip="Back to scorers"
                        to={urls.aiObservabilityScorers()}
                        disabledReason={saving ? 'Saving scorer' : undefined}
                    />
                    <h2 className="text-base font-semibold m-0 truncate" title={definition?.name}>
                        {isNew ? 'New scorer' : definition?.name || 'Scorer'}
                    </h2>
                </nav>
                {todayRailNav ? (
                    <QuillAIObservabilityScorerActions {...props} />
                ) : (
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
                                            openCreateScorerVersionDialog({
                                                currentVersion: definition.current_version,
                                                createVersion,
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
                                <LemonButton
                                    icon={<IconEllipsis />}
                                    aria-label="Scorer actions"
                                    type="secondary"
                                    size="small"
                                />
                            </LemonMenu>
                        )}
                        <LemonButton
                            to={urls.aiObservabilityScorers()}
                            type="secondary"
                            size="small"
                            disabledReason={saving ? 'Saving scorer' : undefined}
                            data-attr="llma-scorer-cancel"
                        >
                            {hasChanges || isNew ? 'Cancel' : 'Back to scorers'}
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            size="small"
                            htmlType="submit"
                            form="scorer-form"
                            loading={saving}
                            disabledReason={editDisabledReason || (!hasChanges ? 'No unsaved changes' : undefined)}
                            data-attr="llma-scorer-save"
                        >
                            {isNew ? 'Create scorer' : 'Save changes'}
                        </LemonButton>
                    </div>
                )}
            </div>
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
        </ScorersScene>
    )
}
