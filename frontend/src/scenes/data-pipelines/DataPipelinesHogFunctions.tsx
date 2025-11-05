import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { humanizeHogFunctionType } from 'scenes/hog-functions/hog-function-utils'
import { HogFunctionTemplateList } from 'scenes/hog-functions/list/HogFunctionTemplateList'
import { HogFunctionList } from 'scenes/hog-functions/list/HogFunctionsList'
import { hogFunctionsListLogic } from 'scenes/hog-functions/list/hogFunctionsListLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { HogFunctionTypeType, ProductKey } from '~/types'

import { nonHogFunctionTemplatesLogic } from './utils/nonHogFunctionTemplatesLogic'
import { nonHogFunctionsLogic } from './utils/nonHogFunctionsLogic'

export type DataPipelinesHogFunctionsProps = {
    kind: HogFunctionTypeType
    additionalKinds?: HogFunctionTypeType[]
    action?: JSX.Element
}

export const MAPPING: Partial<Record<HogFunctionTypeType, { key: ProductKey; description: string }>> = {
    destination: {
        key: ProductKey.PIPELINE_DESTINATIONS,
        description: 'Destinations allow you to send your data to external systems.',
    },
    transformation: {
        key: ProductKey.PIPELINE_TRANSFORMATIONS,
        description:
            'Transformations let you modify, filter, and enrich event data to improve data quality, privacy, and consistency.',
    },
    site_app: {
        key: ProductKey.SITE_APPS,
        description: 'Site apps allow you to add custom functionality to your website using PostHog.',
    },
}

export function DataPipelinesHogFunctions({
    kind,
    additionalKinds,
    action,
}: DataPipelinesHogFunctionsProps): JSX.Element {
    const humanizedKind = humanizeHogFunctionType(kind)
    const logicKey = `data-pipelines-hog-functions-${kind}`

    const { hogFunctions, loading } = useValues(
        hogFunctionsListLogic({ logicKey, type: kind, additionalTypes: additionalKinds })
    )

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

    const productInfoMapping = MAPPING[kind]

    return (
        <SceneContent>
            {productInfoMapping ? (
                <ProductIntroduction
                    productName={`Pipeline ${humanizedKind}s`}
                    thingName={humanizedKind}
                    productKey={productInfoMapping.key}
                    description={productInfoMapping.description}
                    docsURL="https://posthog.com/docs/cdp"
                    actionElementOverride={action}
                    isEmpty={hogFunctions.length === 0 && !loading}
                />
            ) : null}
            <SceneSection>
                <HogFunctionList
                    logicKey={logicKey}
                    type={kind}
                    additionalTypes={additionalKinds}
                    manualFunctions={
                        kind === 'destination'
                            ? [...(hogFunctionPluginsDestinations ?? []), ...(hogFunctionBatchExports ?? [])]
                            : kind === 'site_app'
                              ? [...(hogFunctionPluginsSiteApps ?? [])]
                              : undefined
                    }
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
