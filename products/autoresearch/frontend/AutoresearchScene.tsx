import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconPause, IconPlay, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonTable, LemonTableColumn, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { dayjs } from 'lib/dayjs'
import { createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { autoresearchLogic } from './autoresearchLogic'
import { AutoresearchPipelineApi, AutoresearchPipelineStatusEnumApi } from './generated/api.schemas'

export const scene: SceneExport = {
    component: AutoresearchScene,
    logic: autoresearchLogic,
    productKey: ProductKey.AUTORESEARCH,
}

const STATUS_TAG_TYPE: Record<
    AutoresearchPipelineStatusEnumApi,
    'default' | 'success' | 'warning' | 'danger' | 'highlight' | 'completion'
> = {
    draft: 'default',
    bootstrapping: 'highlight',
    running: 'success',
    converged: 'completion',
    paused: 'warning',
    archived: 'default',
}

const STATUS_LABEL: Record<AutoresearchPipelineStatusEnumApi, string> = {
    draft: 'Draft',
    bootstrapping: 'Bootstrapping',
    running: 'Running',
    converged: 'Converged',
    paused: 'Paused',
    archived: 'Archived',
}

export const STATUS_DESCRIPTION: Record<AutoresearchPipelineStatusEnumApi, string> = {
    draft: 'Created but never trained. Start a training run to find a first champion.',
    bootstrapping: 'First training run in progress — no champion has been promoted yet.',
    running: 'Live: a champion is promoted and the population is scored on schedule.',
    converged: 'Champion is stable (budget spent or improvement plateaued); still scoring on schedule.',
    paused: 'Scheduled scoring is on hold. Resume to continue scoring.',
    archived: 'Retired. No training or scoring runs.',
}

export function AutoresearchScene(): JSX.Element {
    const { pipelines, pipelinesLoading } = useValues(autoresearchLogic)
    const { deletePipeline, pausePipeline, resumePipeline } = useActions(autoresearchLogic)
    const isEmpty = pipelines.length === 0 && !pipelinesLoading

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
            render: (days: AutoresearchPipelineApi['horizon_days']) => (days ? `${days}d` : '—'),
        },
        {
            title: 'Status',
            dataIndex: 'status',
            render: (status: AutoresearchPipelineApi['status']) => (
                <Tooltip title={STATUS_DESCRIPTION[status]}>
                    <LemonTag type={STATUS_TAG_TYPE[status]}>{STATUS_LABEL[status]}</LemonTag>
                </Tooltip>
            ),
        },
        createdByColumn<AutoresearchPipelineApi>() as LemonTableColumn<
            AutoresearchPipelineApi,
            keyof AutoresearchPipelineApi | undefined
        >,
        {
            title: 'Holdout AUC',
            dataIndex: 'champion_holdout_auc',
            tooltip: 'Offline AUC of the current champion model, measured on held-out training data.',
            render: (auc: AutoresearchPipelineApi['champion_holdout_auc']) => (auc == null ? '—' : auc.toFixed(3)),
        },
        {
            title: 'Online accuracy',
            dataIndex: 'champion_realized_auc',
            tooltip:
                'Realized AUC of the current champion model, measured against actual outcomes once predictions matured.',
            render: (auc: AutoresearchPipelineApi['champion_realized_auc']) => (auc == null ? '—' : auc.toFixed(3)),
        },
        {
            title: 'Last scored',
            dataIndex: 'last_scored_at',
            render: (ts: AutoresearchPipelineApi['last_scored_at']) => (ts ? dayjs(ts).fromNow() : 'Never'),
        },
        {
            title: '',
            width: 0,
            render: (_: unknown, record: AutoresearchPipelineApi) => {
                const canPause = record.status === 'running' || record.status === 'bootstrapping'
                const canResume = record.status === 'paused'
                return (
                    <div className="flex items-center gap-1">
                        {canPause && (
                            <LemonButton
                                size="small"
                                icon={<IconPause />}
                                tooltip="Pause — put daily scoring on hold"
                                onClick={(e) => {
                                    e.stopPropagation()
                                    pausePipeline(record)
                                }}
                            />
                        )}
                        {canResume && (
                            <LemonButton
                                size="small"
                                icon={<IconPlay />}
                                tooltip="Resume daily scoring"
                                onClick={(e) => {
                                    e.stopPropagation()
                                    resumePipeline(record)
                                }}
                            />
                        )}
                        <LemonButton
                            size="small"
                            icon={<IconTrash />}
                            status="danger"
                            tooltip="Delete pipeline"
                            onClick={(e) => {
                                e.stopPropagation()
                                LemonDialog.open({
                                    title: `Delete "${record.name}"?`,
                                    description:
                                        'The pipeline, its training runs, models, and predictions metadata will be removed. Emitted autoresearch_prediction events stay in the events stream.',
                                    primaryButton: {
                                        children: 'Delete',
                                        status: 'danger',
                                        onClick: () => deletePipeline(record.id, record.name),
                                    },
                                    secondaryButton: { children: 'Cancel' },
                                })
                            }}
                        />
                    </div>
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
                    <LemonButton type="primary" icon={<IconPlus />} size="small" to={urls.autoresearchNew()}>
                        New model
                    </LemonButton>
                }
            />

            <ProductIntroduction
                isEmpty={isEmpty}
                productName="Autoresearch"
                productKey={ProductKey.AUTORESEARCH}
                thingName="prediction pipeline"
                description="Autoresearch automatically finds the best model to predict user behavior, scoring your users daily and emitting predictions as PostHog events."
                action={() => router.actions.push(urls.autoresearchNew())}
                className="my-0"
            />

            {!isEmpty && <LemonTable loading={pipelinesLoading} columns={columns} dataSource={pipelines} rowKey="id" />}
        </SceneContent>
    )
}
