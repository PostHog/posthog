import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { humanizeHogFunctionType } from 'scenes/hog-functions/hog-function-utils'
import { HogFunctionList } from 'scenes/hog-functions/list/HogFunctionsList'
import { hogFunctionsListLogic } from 'scenes/hog-functions/list/hogFunctionsListLogic'
import { HogFunctionTemplateList } from 'scenes/hog-functions/list/HogFunctionTemplateList'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { HogFunctionType, HogFunctionTypeType } from '~/types'

import { nonHogFunctionsLogic } from './utils/nonHogFunctionsLogic'
import { nonHogFunctionTemplatesLogic } from './utils/nonHogFunctionTemplatesLogic'

export type DataPipelinesHogFunctionsProps = {
    kind: HogFunctionTypeType
    additionalKinds?: HogFunctionTypeType[]
    action?: JSX.Element
}

// `site_app` is intentionally absent: web scripts renders the scene-level product
// empty state instead (products/cdp/frontend/emptyState).
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

    // Each source is null until it loads, so keep them unflattened here: the list just needs
    // everything in one array, but the empty state has to tell "none" apart from "not loaded yet".
    const manualSources: (HogFunctionType[] | null)[] =
        kind === 'destination'
            ? [hogFunctionPluginsDestinations, hogFunctionBatchExports]
            : kind === 'site_app'
              ? [hogFunctionPluginsSiteApps]
              : []

    const manualFunctions = manualSources.length > 0 ? manualSources.flatMap((source) => source ?? []) : undefined

    // A null source has not loaded yet. Counting it as empty flashes the CTA before the data arrives.
    const isEmpty =
        !loading && hogFunctions.length === 0 && manualSources.every((source) => source !== null && source.length === 0)

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
                    isEmpty={isEmpty}
                />
            ) : null}
            <SceneSection>
                <HogFunctionList
                    logicKey={logicKey}
                    type={kind}
                    additionalTypes={additionalKinds}
                    manualFunctions={manualFunctions}
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
