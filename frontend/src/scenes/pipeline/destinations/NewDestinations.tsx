import { IconPlusSmall } from '@posthog/icons'
import { useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { BatchExportService, HogFunctionTemplateType, PluginType } from '~/types'

import { HogFunctionIcon } from './hogfunctions/HogFunctionIcon'
import { PIPELINE_TAB_TO_NODE_STAGE } from './PipelineNode'
import { pipelineNodeNewLogic, PipelineNodeNewLogicProps } from './pipelineNodeNewLogic'
import { PipelineBackend } from './types'
import { getBatchExportUrl, RenderApp, RenderBatchExportIcon } from './utils'

const paramsToProps = ({
    params: { stage, id },
}: {
    params: { stage?: string; id?: string }
}): PipelineNodeNewLogicProps => {
    const numericId = id && /^\d+$/.test(id) ? parseInt(id) : undefined
    const pluginId = numericId && !isNaN(numericId) ? numericId : null
    const hogFunctionId = pluginId ? null : id?.startsWith('hog-') ? id.slice(4) : null
    const batchExportDestination = hogFunctionId ? null : id ?? null

    return {
        stage: PIPELINE_TAB_TO_NODE_STAGE[stage + 's'] || null, // pipeline tab has stage plural here we have singular
        pluginId,
        batchExportDestination,
        hogFunctionId,
    }
}

export const scene: SceneExport = {
    component: PipelineNodeNew,
    logic: pipelineNodeNewLogic,
    paramsToProps,
}

type TableEntry = {
    backend: PipelineBackend
    id: string | number
    name: string
    description: string
    url?: string
    icon: JSX.Element
}

function convertPluginToTableEntry(plugin: PluginType): TableEntry {
    return {
        backend: PipelineBackend.Plugin,
        id: plugin.id,
        name: plugin.name,
        description: plugin.description || '',
        icon: <RenderApp plugin={plugin} />,
        // TODO: ideally we'd link to docs instead of GitHub repo, so it can open in panel
        // Same for transformations and destinations tables
        url: plugin.url,
    }
}

function convertBatchExportToTableEntry(service: BatchExportService['type']): TableEntry {
    return {
        backend: PipelineBackend.BatchExport,
        id: service as string,
        name: service,
        description: `${service} batch export`,
        icon: <RenderBatchExportIcon type={service} />,
        url: getBatchExportUrl(service),
    }
}

function convertHogFunctionToTableEntry(hogFunction: HogFunctionTemplateType): TableEntry {
    return {
        backend: PipelineBackend.HogFunction,
        id: `hog-${hogFunction.id}`, // TODO: This weird identifier thing isn't great
        name: hogFunction.name,
        description: hogFunction.description,
        icon: <HogFunctionIcon size="small" src={hogFunction.icon_url} />,
    }
}

export function DestinationOptionsTable(): JSX.Element {
    const hogFunctionsEnabled = !!useFeatureFlag('HOG_FUNCTIONS')
    const { batchExportServiceNames, plugins, loading, hogFunctionTemplates } = useValues(pipelineNodeNewLogic)
    const pluginTargets = Object.values(plugins).map(convertPluginToTableEntry)
    const batchExportTargets = Object.values(batchExportServiceNames).map(convertBatchExportToTableEntry)
    const hogFunctionTargets = hogFunctionsEnabled
        ? Object.values(hogFunctionTemplates).map(convertHogFunctionToTableEntry)
        : []
    const targets = [...hogFunctionTargets, ...batchExportTargets, ...pluginTargets]

    const { hashParams } = useValues(router)
    return (
        <>
            <LemonTable
                dataSource={targets}
                size="small"
                loading={loading}
                columns={[
                    {
                        title: 'App',
                        width: 0,
                        render: function RenderAppInfo(_, target) {
                            return target.icon
                        },
                    },
                    {
                        title: 'Name',
                        sticky: true,
                        render: function RenderName(_, target) {
                            return (
                                <LemonTableLink
                                    to={urls.pipelineNodeNew(stage, target.id)}
                                    title={target.name}
                                    description={target.description}
                                />
                            )
                        },
                    },
                    {
                        title: 'Actions',
                        width: 100,
                        align: 'right',
                        render: function RenderActions(_, target) {
                            return (
                                <LemonButton
                                    type="primary"
                                    data-attr={`new-${stage}-${target.id}`}
                                    icon={<IconPlusSmall />}
                                    // Preserve hash params to pass config in
                                    to={combineUrl(urls.pipelineNodeNew(stage, target.id), {}, hashParams).url}
                                >
                                    Create
                                </LemonButton>
                            )
                        },
                    },
                ]}
            />
        </>
    )
}
