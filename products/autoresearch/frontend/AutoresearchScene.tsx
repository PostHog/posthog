import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonTable, LemonTableColumn, LemonTag } from '@posthog/lemon-ui'

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
    'default' | 'success' | 'warning' | 'danger' | 'purple' | 'completion'
> = {
    draft: 'default',
    bootstrapping: 'purple',
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

export function AutoresearchScene(): JSX.Element {
    const { pipelines, pipelinesLoading } = useValues(autoresearchLogic)
    const { deletePipeline } = useActions(autoresearchLogic)
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
                <LemonTag type={STATUS_TAG_TYPE[status]}>{STATUS_LABEL[status]}</LemonTag>
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
            render: (_: unknown, record: AutoresearchPipelineApi) => (
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
            ),
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
                        New prediction
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
