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

export function DataPipelinesHogFunctions({ kind, additionalKinds }: DataPipelinesHogFunctionsProps): JSX.Element {
    const humanizedKind = humanizeHogFunctionType(kind)
    const logicKey = `data-pipelines-hog-functions-${kind}`

    const { hogFunctions } = useValues(hogFunctionListLogic({ logicKey, type: kind }))

    const newButton = (
        <LemonButton to={urls.dataPipelinesNew(kind)} type="primary" icon={<IconPlusSmall />} size="small">
            New {humanizedKind}
        </LemonButton>
    )
    return (
        <>
            {/* TODO: Genericize this */}
            <PageHeader
                caption="Transform your incoming events before they are stored in PostHog or sent on to Destinations."
                buttons={newButton}
            />
            <ProductIntroduction
                productName="Pipeline transformations"
                thingName="transformation"
                productKey={ProductKey.PIPELINE_TRANSFORMATIONS}
                description="Pipeline transformations allow you to enrich your data with additional information, such as geolocation."
                docsURL="https://posthog.com/docs/cdp"
                actionElementOverride={newButton}
                isEmpty={hogFunctions.length === 0}
            />
            <div>
                <HogFunctionList logicKey={logicKey} type={kind} extraControls={<>{newButton}</>} />
                <div>
                    <h2 className="mt-4">Create a new {humanizedKind}</h2>
                    <HogFunctionTemplateList defaultFilters={{}} type={kind} />
                </div>
            </div>
        </>
    )
}
