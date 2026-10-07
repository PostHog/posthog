import { useActions, useValues } from 'kea'

import { IconPause, IconPlay, IconPlus, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDialog, LemonTable, LemonTableColumn } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { autoresearchLogic } from './autoresearchLogic'
import { autoresearchEmptyState } from './emptyState/autoresearchEmptyState'
import { AutoresearchPipelineApi } from './generated/api.schemas'
import { MODEL_QUALITY_THRESHOLDS, modelQuality } from './modelQuality'
import { ModelQualityTag } from './ModelQualityTag'
import { PipelineStatusTag } from './PipelineStatusTag'

export const scene: SceneExport = {
    component: AutoresearchScene,
    logic: autoresearchLogic,
    productKey: ProductKey.AUTORESEARCH,
    emptyState: autoresearchEmptyState,
}

export function AutoresearchScene(): JSX.Element {
    const isEnabled = useFeatureFlag('AUTORESEARCH')
    const { pipelines, pipelinesLoading, pipelinesLoadFailed, mutatingPipelineIds } = useValues(autoresearchLogic)
    const { deletePipeline, pausePipeline, resumePipeline, loadPipelines } = useActions(autoresearchLogic)

    if (!isEnabled) {
        return <NotFound object="Autoresearch" caption="This feature is not enabled for your project." />
    }

    const columns: LemonTableColumn<AutoresearchPipelineApi, keyof AutoresearchPipelineApi | undefined>[] = [
        {
            title: 'Name',
            sticky: true,
            render: (_: unknown, record: AutoresearchPipelineApi) => (
                <LemonTableLink
                    to={urls.autoresearchPipeline(record.id)}
                    title={record.name}
                    description={record.description}
                />
            ),
        },
        {
            title: 'Target',
            dataIndex: 'target_event',
        },
        {
            title: 'Prediction horizon',
            dataIndex: 'horizon_days',
            render: (_, record: AutoresearchPipelineApi) => (record.horizon_days ? `${record.horizon_days}d` : '—'),
        },
        {
            title: 'Status',
            dataIndex: 'status',
            render: (_, record: AutoresearchPipelineApi) => <PipelineStatusTag status={record.status} />,
        },
        createdByColumn() as unknown as LemonTableColumn<
            AutoresearchPipelineApi,
            keyof AutoresearchPipelineApi | undefined
        >,
        {
            title: 'Quality',
            tooltip: `How well the current champion model ranks people. Strong is an AUC of ${MODEL_QUALITY_THRESHOLDS.strong.toFixed(2)} or more, Fair is ${MODEL_QUALITY_THRESHOLDS.fair.toFixed(2)} to ${MODEL_QUALITY_THRESHOLDS.strong.toFixed(2)}, and Weak is below ${MODEL_QUALITY_THRESHOLDS.fair.toFixed(2)}. Realized AUC from real outcomes is used when it exists, otherwise holdout AUC from test data.`,
            render: (_, record: AutoresearchPipelineApi) => {
                const quality = modelQuality({
                    holdoutAuc: record.champion_holdout_auc,
                    realizedAuc: record.champion_realized_auc,
                    liftAt10: record.champion_lift_at_10,
                    isPreliminary: record.champion_is_preliminary,
                    target: record.target_event,
                })
                if (!quality) {
                    return <span className="text-secondary">—</span>
                }
                return (
                    <div className="flex flex-col gap-0.5">
                        <div className="flex items-center gap-1">
                            <ModelQualityTag
                                quality={quality}
                                holdoutAuc={record.champion_holdout_auc}
                                realizedAuc={record.champion_realized_auc}
                            />
                            <span className="text-xs text-secondary">{quality.basis}</span>
                        </div>
                        <span className="text-xs text-secondary">{quality.sentence}</span>
                    </div>
                )
            },
        },
        {
            title: 'Last scored',
            dataIndex: 'last_scored_at',
            render: (_, record: AutoresearchPipelineApi) =>
                record.last_scored_at ? dayjs(record.last_scored_at).fromNow() : 'Never',
        },
        {
            title: '',
            width: 0,
            render: (_: unknown, record: AutoresearchPipelineApi) => {
                const canPause = record.status === 'running'
                const canResume = record.status === 'paused'
                const mutating = !!mutatingPipelineIds[record.id]
                return (
                    <More
                        data-attr="autoresearch-model-more"
                        overlay={
                            <>
                                {canPause && (
                                    <LemonButton
                                        fullWidth
                                        icon={<IconPause />}
                                        loading={mutating}
                                        disabledReason={mutating ? 'Another change is still saving' : undefined}
                                        onClick={() => pausePipeline(record)}
                                    >
                                        Pause scheduled scoring
                                    </LemonButton>
                                )}
                                {canResume && (
                                    <LemonButton
                                        fullWidth
                                        icon={<IconPlay />}
                                        loading={mutating}
                                        disabledReason={mutating ? 'Another change is still saving' : undefined}
                                        onClick={() => resumePipeline(record)}
                                    >
                                        Resume scheduled scoring
                                    </LemonButton>
                                )}
                                <LemonButton
                                    fullWidth
                                    icon={<IconTrash />}
                                    status="danger"
                                    loading={mutating}
                                    disabledReason={
                                        mutating
                                            ? 'Another change is still saving'
                                            : record.status === 'bootstrapping'
                                              ? 'Wait for the first training run to finish'
                                              : undefined
                                    }
                                    onClick={() => {
                                        LemonDialog.open({
                                            title: `Delete "${record.name}"?`,
                                            description:
                                                'The model, its training runs, and prediction metadata will be removed. Emitted autoresearch_prediction events stay in the events stream, and the prediction person property stays on each scored person.',
                                            primaryButton: {
                                                children: 'Delete',
                                                status: 'danger',
                                                onClick: () => deletePipeline(record.id, record.name),
                                            },
                                            secondaryButton: { children: 'Cancel' },
                                        })
                                    }}
                                >
                                    Delete model
                                </LemonButton>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.Autoresearch].name ?? 'Autoresearch'}
                description={sceneConfigurations[Scene.Autoresearch].description}
                resourceType={{
                    type: sceneConfigurations[Scene.Autoresearch].iconType ?? 'experiment',
                }}
                actions={
                    <LemonButton
                        type="primary"
                        icon={<IconPlus />}
                        size="small"
                        to={urls.autoresearchNew()}
                        data-attr="autoresearch-new-model"
                    >
                        New model
                    </LemonButton>
                }
            />

            {pipelinesLoadFailed && !pipelinesLoading && (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Retry',
                        onClick: () => loadPipelines(),
                        'data-attr': 'autoresearch-list-retry',
                    }}
                >
                    Couldn't load your models. Try again, and if it keeps happening contact support.
                </LemonBanner>
            )}
            {!(pipelinesLoadFailed && pipelines.length === 0) && (
                <LemonTable loading={pipelinesLoading} columns={columns} dataSource={pipelines} rowKey="id" />
            )}
        </SceneContent>
    )
}
