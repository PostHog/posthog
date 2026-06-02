import { actions, afterMount, connect, kea, listeners, path } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import type { autoresearchLogicType } from './autoresearchLogicType'
import {
    autoresearchDestroy,
    autoresearchList,
    autoresearchPauseCreate,
    autoresearchResumeCreate,
} from './generated/api'
import { AutoresearchPipelineApi } from './generated/api.schemas'

export const autoresearchLogic = kea<autoresearchLogicType>([
    path(['products', 'autoresearch', 'autoresearchLogic']),
    connect({
        values: [teamLogic, ['currentTeamId']],
    }),
    actions({
        deletePipeline: (id: string, name: string) => ({ id, name }),
        pausePipeline: (pipeline: AutoresearchPipelineApi) => ({ pipeline }),
        resumePipeline: (pipeline: AutoresearchPipelineApi) => ({ pipeline }),
    }),
    loaders(({ values }) => ({
        pipelines: [
            [] as AutoresearchPipelineApi[],
            {
                loadPipelines: async () => {
                    if (!values.currentTeamId) {
                        return []
                    }
                    const response = await autoresearchList(String(values.currentTeamId))
                    return response.results
                },
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        deletePipeline: async ({ id, name }: { id: string; name: string }) => {
            if (!values.currentTeamId) {
                return
            }
            try {
                await autoresearchDestroy(String(values.currentTeamId), id)
                lemonToast.success(`Deleted "${name}"`)
                actions.loadPipelines()
            } catch (error: any) {
                lemonToast.error(error?.detail ?? error?.data?.detail ?? 'Failed to delete pipeline')
            }
        },
        pausePipeline: async ({ pipeline }: { pipeline: AutoresearchPipelineApi }) => {
            if (!values.currentTeamId) {
                return
            }
            try {
                // The endpoint only flips status, but the generated client types a body — pass the record.
                await autoresearchPauseCreate(String(values.currentTeamId), pipeline.id, pipeline)
                lemonToast.success(`Paused "${pipeline.name}" — daily scoring is on hold`)
                actions.loadPipelines()
            } catch (error: any) {
                lemonToast.error(error?.detail ?? error?.data?.detail ?? 'Failed to pause pipeline')
            }
        },
        resumePipeline: async ({ pipeline }: { pipeline: AutoresearchPipelineApi }) => {
            if (!values.currentTeamId) {
                return
            }
            try {
                await autoresearchResumeCreate(String(values.currentTeamId), pipeline.id, pipeline)
                lemonToast.success(`Resumed "${pipeline.name}"`)
                actions.loadPipelines()
            } catch (error: any) {
                lemonToast.error(error?.detail ?? error?.data?.detail ?? 'Failed to resume pipeline')
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadPipelines()
    }),
])
