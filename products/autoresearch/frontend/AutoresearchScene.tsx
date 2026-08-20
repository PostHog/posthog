import { useActions, useValues } from 'kea'

import { IconPause, IconPlay, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonTable, LemonTableColumn } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
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
import { PipelineStatusTag } from './PipelineStatusTag'

export const scene: SceneExport = {
    component: AutoresearchScene,
    logic: autoresearchLogic,
    productKey: ProductKey.AUTORESEARCH,
    emptyState: autoresearchEmptyState,
}

export function AutoresearchScene(): JSX.Element {
    const { pipelines, pipelinesLoading, mutatingPipelineIds } = useValues(autoresearchLogic)
    const { deletePipeline, pausePipeline, resumePipeline } = useActions(autoresearchLogic)

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
            title: 'Holdout AUC',
            dataIndex: 'champion_holdout_auc',
            tooltip: 'Offline AUC of the current champion model, measured on held-out training data.',
            render: (_, record: AutoresearchPipelineApi) =>
                record.champion_holdout_auc == null ? '—' : record.champion_holdout_auc.toFixed(3),
        },
        {
            title: 'Realized AUC',
            dataIndex: 'champion_realized_auc',
            tooltip:
                'Realized AUC of the current champion model, measured against actual outcomes once predictions matured.',
            render: (_, record: AutoresearchPipelineApi) =>
                record.champion_realized_auc == null ? '—' : record.champion_realized_auc.toFixed(3),
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
                const canPause = record.status === 'running' || record.status === 'bootstrapping'
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
                                        Pause daily scoring
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
                                        Resume daily scoring
                                    </LemonButton>
                                )}
                                <LemonButton
                                    fullWidth
                                    icon={<IconTrash />}
                                    status="danger"
                                    loading={mutating}
                                    disabledReason={mutating ? 'Another change is still saving' : undefined}
                                    onClick={() => {
                                        LemonDialog.open({
                                            title: `Delete "${record.name}"?`,
                                            description:
                                                'The model, its training runs, and prediction metadata will be removed. Emitted autoresearch_prediction events stay in the events stream.',
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
                    <LemonButton type="primary" icon={<IconPlus />} size="small" to={urls.autoresearchNew()}>
                        New model
                    </LemonButton>
                }
            />

            <LemonTable loading={pipelinesLoading} columns={columns} dataSource={pipelines} rowKey="id" />
        </SceneContent>
    )
}
