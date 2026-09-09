import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { humanizeHogFunctionType } from 'scenes/hog-functions/hog-function-utils'
import { HogFunctionList } from 'scenes/hog-functions/list/HogFunctionsList'
import { HogFunctionTemplateList } from 'scenes/hog-functions/list/HogFunctionTemplateList'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { HogFunctionType, HogFunctionTypeType } from '~/types'

import { nonHogFunctionsLogic } from './utils/nonHogFunctionsLogic'
import { nonHogFunctionTemplatesLogic } from './utils/nonHogFunctionTemplatesLogic'

export type DataPipelinesHogFunctionsProps = {
    kind: HogFunctionTypeType
    additionalKinds?: HogFunctionTypeType[]
}

export function DataPipelinesHogFunctions({ kind, additionalKinds }: DataPipelinesHogFunctionsProps): JSX.Element {
    const humanizedKind = humanizeHogFunctionType(kind)
    const logicKey = `data-pipelines-hog-functions-${kind}`

    const { hogFunctionPluginsDestinations, hogFunctionBatchExports, hogFunctionPluginsSiteApps } =
        useValues(nonHogFunctionsLogic)
    const { loadHogFunctionPluginsDestinations, loadHogFunctionBatchExports, loadHogFunctionPluginsSiteApps } =
        useActions(nonHogFunctionsLogic)

    const { hogFunctionTemplatesBatchExports } = useValues(nonHogFunctionTemplatesLogic)

    useEffect(() => {
        if (kind === 'destination') {
            loadHogFunctionPluginsDestinations()
            loadHogFunctionBatchExports()
        }

        if (kind === 'site_app') {
            loadHogFunctionPluginsSiteApps()
        }
    }, [kind]) // oxlint-disable-line react-hooks/exhaustive-deps

    // Each source is null until it loads; the list just needs everything in one array.
    const manualSources: (HogFunctionType[] | null)[] =
        kind === 'destination'
            ? [hogFunctionPluginsDestinations, hogFunctionBatchExports]
            : kind === 'site_app'
              ? [hogFunctionPluginsSiteApps]
              : []

    const manualFunctions = manualSources.length > 0 ? manualSources.flatMap((source) => source ?? []) : undefined

    return (
        <SceneContent>
            <SceneSection>
                <HogFunctionList
                    logicKey={logicKey}
                    type={kind}
                    additionalTypes={additionalKinds}
                    manualFunctions={manualFunctions}
                    truncateDescriptions
                />
            </SceneSection>
            <SceneDivider />
            <SceneSection title={`Create a new ${humanizedKind}`}>
                <HogFunctionTemplateList
                    type={kind}
                    additionalTypes={additionalKinds}
                    manualTemplates={kind === 'destination' ? hogFunctionTemplatesBatchExports : undefined}
                    hideComingSoonByDefault
                />
            </SceneSection>
        </SceneContent>
    )
}
