import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { humanizeHogFunctionType } from 'scenes/hog-functions/hog-function-utils'
import { hogFunctionListLogic } from 'scenes/hog-functions/list/hogFunctionListLogic'
import { HogFunctionList } from 'scenes/hog-functions/list/HogFunctionsList'
import { HogFunctionTemplateList } from 'scenes/hog-functions/list/HogFunctionTemplateList'
import { urls } from 'scenes/urls'

import { HogFunctionTypeType, ProductKey } from '~/types'

export type DataPipelinesHogFunctionsProps = {
    kind: HogFunctionTypeType
    additionalKinds?: HogFunctionTypeType[]
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

export function DataPipelinesHogFunctions({ kind, additionalKinds }: DataPipelinesHogFunctionsProps): JSX.Element {
    const humanizedKind = humanizeHogFunctionType(kind)
    const logicKey = `data-pipelines-hog-functions-${kind}`

    const { hogFunctions, loading } = useValues(
        hogFunctionListLogic({ logicKey, type: kind, additionalTypes: additionalKinds })
    )

    const newButton = (
        <LemonButton to={urls.dataPipelinesNew(kind)} type="primary" icon={<IconPlusSmall />} size="small">
            New {humanizedKind}
        </LemonButton>
    )

    const productInfoMapping = MAPPING[kind]

    return (
        <>
            <PageHeader buttons={newButton} />
            {productInfoMapping ? (
                <ProductIntroduction
                    productName={`Pipeline ${humanizedKind}s`}
                    thingName={humanizedKind}
                    productKey={productInfoMapping.key}
                    description={productInfoMapping.description}
                    docsURL="https://posthog.com/docs/cdp"
                    actionElementOverride={newButton}
                    isEmpty={hogFunctions.length === 0 && !loading}
                />
            ) : null}
            <div>
                <HogFunctionList logicKey={logicKey} type={kind} additionalTypes={additionalKinds} />
                <div>
                    <h2 className="mt-4">Create a new {humanizedKind}</h2>
                    <HogFunctionTemplateList defaultFilters={{}} type={kind} additionalTypes={additionalKinds} />
                </div>
            </div>
        </>
    )
}
