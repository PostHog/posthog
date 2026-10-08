import { Meta, StoryObj } from '@storybook/react'
import { BindLogic, useMountedLogic } from 'kea'
import { useEffect } from 'react'

import { mswDecorator } from '~/mocks/browser'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import {
    AutoresearchModelApi,
    AutoresearchModelRoleEnumApi,
    AutoresearchTrainingRunApi,
    FeatureDirectionEnumApi,
    FeatureImportanceApi,
} from '../generated/api.schemas'
import { TrainingRunRow } from './TrainingRunRow'

const PIPELINE_ID = 'pipeline-story'
const RUN_ID = '0b5e2f1c-7a1d-4c2e-9f3a-5d6e7f8a9b0c'

const RUN: AutoresearchTrainingRunApi = {
    id: RUN_ID,
    pipeline: PIPELINE_ID,
    task_url: null,
    status: 'completed',
    iteration_count: 4,
    best_holdout_score: 0.812,
    summary: null,
    iterations: [
        { iteration_number: 0, status: 'kept', holdout_score: 0.74 },
        { iteration_number: 1, status: 'discarded', holdout_score: 0.71 },
        { iteration_number: 2, status: 'kept', holdout_score: 0.79 },
        { iteration_number: 3, status: 'kept', holdout_score: 0.812 },
    ],
    error: '',
    started_at: '2026-10-01T09:00:00Z',
    completed_at: '2026-10-01T09:42:00Z',
    created_at: '2026-10-01T09:00:00Z',
} as unknown as AutoresearchTrainingRunApi

function feature(name: string, importance: number, negative = false): FeatureImportanceApi {
    return {
        name,
        importance,
        direction: negative ? FeatureDirectionEnumApi.Negative : FeatureDirectionEnumApi.Positive,
    }
}

function makeModel(overrides: Partial<AutoresearchModelApi>): AutoresearchModelApi {
    return {
        id: 'model-run',
        pipeline: PIPELINE_ID,
        role: AutoresearchModelRoleEnumApi.Challenger,
        holdout_score: 0.812,
        source_training_run: RUN_ID,
        model_explanation: {
            method: 'Permutation importance on holdout',
            top_features: [
                feature('pageviews_last_7d', 0.31),
                feature('files_uploaded_last_30d', 0.22),
                feature('days_since_signup', 0.14, true),
                feature('invited_teammates', 0.09),
            ],
        },
        ...overrides,
    } as AutoresearchModelApi
}

const CHAMPION = makeModel({
    id: 'model-champion',
    role: AutoresearchModelRoleEnumApi.Champion,
    holdout_score: 0.834,
    source_training_run: 'run-older',
    model_explanation: {
        method: 'Permutation importance on holdout',
        top_features: [
            feature('pageviews_last_7d', 0.35),
            feature('files_uploaded_last_30d', 0.2),
            feature('dashboards_viewed_last_30d', 0.12),
            feature('days_since_signup', 0.08, true),
        ],
    },
})

// 520px is about the scene width next to the nav sidebar and an open side panel.
const WIDTH_CLASS = { narrow: 'w-[520px]', wide: 'w-[1100px]' }

function ExpandedRunRow({
    models,
    width,
}: {
    models: AutoresearchModelApi[]
    width: keyof typeof WIDTH_CLASS
}): JSX.Element {
    const logic = autoresearchPipelineLogic({ id: PIPELINE_ID })
    useMountedLogic(logic)
    useEffect(() => {
        logic.actions.loadModelsSuccess(models)
        if (logic.values.expandedRunId !== RUN_ID) {
            logic.actions.toggleRunArtifacts(RUN_ID)
        }
    }, [logic, models])
    return (
        <BindLogic logic={autoresearchPipelineLogic} props={{ id: PIPELINE_ID }}>
            <div className={WIDTH_CLASS[width]}>
                <TrainingRunRow run={RUN} />
            </div>
        </BindLogic>
    )
}

const meta: Meta<typeof ExpandedRunRow> = {
    title: 'Products/Autoresearch/Training run row',
    component: ExpandedRunRow,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/autoresearch/:pipeline_id/training_runs/:id/artifacts/': {
                    paths: ['features.sql', 'train.py', 'predict.py'],
                },
            },
            post: {
                '/api/projects/:team_id/autoresearch/:pipeline_id/training_runs/:id/artifacts/get/': [
                    404,
                    { detail: 'Not found.' },
                ],
            },
        }),
    ],
    parameters: { testOptions: { waitForSelector: '.LemonCollapse' } },
}
export default meta
type Story = StoryObj<typeof ExpandedRunRow>

export const ComparedWithChampionWide: Story = {
    args: { models: [makeModel({}), CHAMPION], width: 'wide' },
}

export const ComparedWithChampionNarrow: Story = {
    args: { models: [makeModel({}), CHAMPION], width: 'narrow' },
}

export const RunProducedTheChampion: Story = {
    args: {
        models: [makeModel({ role: AutoresearchModelRoleEnumApi.Champion })],
        width: 'wide',
    },
}

export const RunModelWithoutImportances: Story = {
    args: { models: [makeModel({ model_explanation: {} }), CHAMPION], width: 'wide' },
}
