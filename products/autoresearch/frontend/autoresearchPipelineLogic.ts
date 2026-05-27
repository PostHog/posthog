import { actions, afterMount, connect, kea, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import type { autoresearchPipelineLogicType } from './autoresearchPipelineLogicType'
import {
    autoresearchModelsList,
    autoresearchRetrieve,
    autoresearchRunsList,
    autoresearchSuggestionsList,
    autoresearchTrainingRunsList,
    autoresearchTrainCreate,
} from './generated/api'
import type {
    AutoresearchModelApi,
    AutoresearchPipelineApi,
    AutoresearchRunApi,
    AutoresearchSuggestionApi,
    AutoresearchTrainingRunApi,
} from './generated/api.schemas'

export interface AutoresearchPipelineLogicProps {
    id: string
}

export type AutoresearchPipelineTab =
    | 'overview'
    | 'training'
    | 'models'
    | 'predictions'
    | 'validation'
    | 'runs'
    | 'settings'

export const autoresearchPipelineLogic = kea<autoresearchPipelineLogicType>([
    path(['products', 'autoresearch', 'autoresearchPipelineLogic']),
    props({} as AutoresearchPipelineLogicProps),
    connect({
        values: [teamLogic, ['currentTeamId']],
    }),
    actions({
        setActiveTab: (tab: AutoresearchPipelineTab) => ({ tab }),
    }),
    reducers({
        activeTab: [
            'overview' as AutoresearchPipelineTab,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
    }),
    loaders(({ values, props }) => ({
        pipeline: [
            null as AutoresearchPipelineApi | null,
            {
                loadPipeline: async () => {
                    if (!values.currentTeamId) {
                        return null
                    }
                    return autoresearchRetrieve(String(values.currentTeamId), props.id)
                },
            },
        ],
        models: [
            [] as AutoresearchModelApi[],
            {
                loadModels: async () => {
                    if (!values.currentTeamId) {
                        return []
                    }
                    const response = await autoresearchModelsList(String(values.currentTeamId), props.id)
                    return response.results
                },
            },
        ],
        trainingRuns: [
            [] as AutoresearchTrainingRunApi[],
            {
                loadTrainingRuns: async () => {
                    if (!values.currentTeamId) {
                        return []
                    }
                    const response = await autoresearchTrainingRunsList(String(values.currentTeamId), props.id)
                    return response.results
                },
            },
        ],
        runs: [
            [] as AutoresearchRunApi[],
            {
                loadRuns: async () => {
                    if (!values.currentTeamId) {
                        return []
                    }
                    const response = await autoresearchRunsList(String(values.currentTeamId), props.id)
                    return response.results
                },
            },
        ],
        suggestions: [
            [] as AutoresearchSuggestionApi[],
            {
                loadSuggestions: async () => {
                    if (!values.currentTeamId) {
                        return []
                    }
                    const response = await autoresearchSuggestionsList(String(values.currentTeamId), props.id)
                    return response.results
                },
            },
        ],
        startTrainingResult: [
            null as AutoresearchTrainingRunApi | null,
            {
                startTraining: async () => {
                    if (!values.currentTeamId) {
                        return null
                    }
                    const result = await autoresearchTrainCreate(String(values.currentTeamId), props.id)
                    return result
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        startTrainingSuccess: () => {
            actions.loadTrainingRuns()
            actions.loadPipeline()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadPipeline()
        actions.loadModels()
        actions.loadTrainingRuns()
        actions.loadRuns()
        actions.loadSuggestions()
    }),
])
