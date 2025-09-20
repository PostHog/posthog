import { useActions } from 'kea'
import { router } from 'kea-router'
import type React from 'react'

import { IconOpenSidebar, IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { ProductIntentContext } from 'lib/utils/product-intents'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/types'

import { BuilderHog3 } from '../hedgehogs'

type EmptyStateProps = {
    title: string
    description: string
    action: {
        to: string
        text: string
    }
    docsUrl?: string
    hog: React.ComponentType<{ className?: string }>
    groupType: TaxonomicFilterGroupType
}

const EmptyState = ({ title, description, action, docsUrl, hog: Hog, groupType }: EmptyStateProps): JSX.Element => {
    const { push } = useActions(router)
    const { addProductIntentForCrossSell } = useActions(teamLogic)

    return (
        <div className="flex gap-4 items-center p-8 mt-4 w-full rounded">
            <div className="w-32 h-32">
                <Hog className="w-full h-full" />
            </div>
            <div className="flex-1 text-center">
                <h2 className="text-lg font-semibold">{title}</h2>
                <p className="mt-2 text-sm text-secondary">{description}</p>
                <div className="flex gap-4 justify-center items-center mt-4">
                    <LemonButton
                        type="primary"
                        icon={<IconPlus />}
                        onClick={() => {
                            addProductIntentForCrossSell({
                                from: ProductKey.PRODUCT_ANALYTICS,
                                to: ProductKey.DATA_WAREHOUSE,
                                intent_context: ProductIntentContext.TAXONOMIC_FILTER_EMPTY_STATE,
                            })

                            push(action.to)
                        }}
                        data-attr={`taxonomic-filter-empty-state-${groupType}-new-button`}
                    >
                        {action.text}
                    </LemonButton>
                    <LemonButton
                        type="tertiary"
                        sideIcon={<IconOpenSidebar className="w-4 h-4" />}
                        to={`${docsUrl}?utm_medium=in-product&utm_campaign=taxonomic-filter-empty-state-docs-link`}
                        data-attr="product-introduction-docs-link"
                        targetBlank
                    >
                        Learn more
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}

type Props = {
    groupType: TaxonomicFilterGroupType
}

const DataWarehouseEmptyState = (): JSX.Element => {
    return (
        <EmptyState
            title="Connect external data"
            groupType={TaxonomicFilterGroupType.DataWarehouse}
            description="Use data warehouse sources to import data from your external data into PostHog."
            action={{
                to: urls.dataWarehouseSourceNew(),
                text: 'New source',
            }}
            docsUrl="https://posthog.com/docs/data-warehouse"
            hog={BuilderHog3}
        />
    )
}

const DefaultEmptyState = (): JSX.Element | null => {
    return null
}

const EMPTY_STATES: Partial<Record<TaxonomicFilterGroupType, () => JSX.Element>> = {
    [TaxonomicFilterGroupType.DataWarehouse]: DataWarehouseEmptyState,
    [TaxonomicFilterGroupType.DataWarehouseProperties]: DataWarehouseEmptyState,
    [TaxonomicFilterGroupType.DataWarehousePersonProperties]: DataWarehouseEmptyState,
} as const

export const taxonomicFilterGroupTypesWithEmptyStates = Object.keys(EMPTY_STATES) as TaxonomicFilterGroupType[]

export const TaxonomicFilterEmptyState = (props: Props): JSX.Element => {
    const EmptyState = EMPTY_STATES[props.groupType]

    if (EmptyState) {
        return <EmptyState />
    }

    return <DefaultEmptyState />
}
