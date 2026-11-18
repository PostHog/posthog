import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { humanizeHogFunctionType } from 'scenes/hog-functions/hog-function-utils'
import { HogFunctionList } from 'scenes/hog-functions/list/HogFunctionsList'
import { HogFunctionTemplateList } from 'scenes/hog-functions/list/HogFunctionTemplateList'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { HogFunctionTypeType } from '~/types'

import { nonHogFunctionsLogic } from './utils/nonHogFunctionsLogic'

export type DataPipelinesHogFunctionsProps = {
    kind: HogFunctionTypeType
    additionalKinds?: HogFunctionTypeType[]
}

export function DataPipelinesHogFunctions({ kind, additionalKinds }: DataPipelinesHogFunctionsProps): JSX.Element {
    const humanizedKind = humanizeHogFunctionType(kind)
    const logicKey = `data-pipelines-hog-functions-${kind}`

    const {
        hogFunctionPluginsDestinations,
        hogFunctionPluginsDestinationsLoading,
        hogFunctionPluginsSiteApps,
        hogFunctionPluginsSiteAppsLoading,
    } = useValues(nonHogFunctionsLogic)
    const { loadHogFunctionPluginsDestinations, loadHogFunctionPluginsSiteApps } = useActions(nonHogFunctionsLogic)

    useEffect(() => {
        if (kind === 'destination') {
            loadHogFunctionPluginsDestinations()
        }

        if (kind === 'site_app') {
            loadHogFunctionPluginsSiteApps()
        }
    }, [kind]) // oxlint-disable-line react-hooks/exhaustive-deps

    // Legacy plugins are listed next to the hog functions until the migration off plugins completes.
    const [manualFunctions, manualFunctionsLoading] =
        kind === 'destination'
            ? [hogFunctionPluginsDestinations, hogFunctionPluginsDestinationsLoading]
            : kind === 'site_app'
              ? [hogFunctionPluginsSiteApps, hogFunctionPluginsSiteAppsLoading]
              : [null, false]

    return (
        <SceneContent>
            <SceneSection>
                <HogFunctionList
                    logicKey={logicKey}
                    type={kind}
                    additionalTypes={additionalKinds}
                    manualFunctions={manualFunctions ?? undefined}
                    manualFunctionsLoading={manualFunctionsLoading}
                    truncateDescriptions
                />
            </SceneSection>
            <SceneDivider />
            <SceneSection title={`Create a new ${humanizedKind}`}>
                <HogFunctionTemplateList type={kind} additionalTypes={additionalKinds} hideComingSoonByDefault />
            </SceneSection>
        </SceneContent>
    )
}
