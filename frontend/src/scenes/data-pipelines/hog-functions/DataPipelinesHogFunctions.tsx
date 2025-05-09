import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { HogFunctionList } from 'scenes/hog-functions/list/HogFunctionsList'
import { HogFunctionTemplateList } from 'scenes/hog-functions/list/HogFunctionTemplateList'
import { urls } from 'scenes/urls'

import { HogFunctionTypeType, ProductKey } from '~/types'

export type DataPipelinesHogFunctionsProps = {
    kind: HogFunctionTypeType
    additionalKinds?: HogFunctionTypeType[]
}

export function DataPipelinesHogFunctions({ kind, additionalKinds }: DataPipelinesHogFunctionsProps): JSX.Element {
    const newButton = (
        <LemonButton to={urls.dataPipelines('overview')} type="primary" icon={<IconPlusSmall />} size="small">
            New {kind}
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
                // isEmpty={shouldShowEmptyState}
            />
            <HogFunctionList
                logicKey={kind}
                type={kind}
                extraControls={
                    <>
                        <LemonButton
                            type="primary"
                            size="small"
                            // disabledReason={newDisabledReason}
                            // onClick={() => setShowNewDestination(true)}
                        >
                            New {kind}
                        </LemonButton>
                    </>
                }
            />
            <HogFunctionTemplateList
                defaultFilters={{}}
                type={kind}
                extraControls={
                    <></>
                    // <>
                    //     <LemonButton type="secondary" size="small" onClick={() => setShowNewDestination(false)}>
                    //         Cancel
                    //     </LemonButton>
                    // </>
                }
            />
        </>
    )
}
