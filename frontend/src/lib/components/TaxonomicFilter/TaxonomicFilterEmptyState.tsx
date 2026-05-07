import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import type React from 'react'

import { IconOpenSidebar, IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { getProjectEventExistence } from 'lib/utils/getAppContext'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { getCoreFilterDefinition } from '~/taxonomy/helpers'

import { BuilderHog3 } from '../hedgehogs'

function labelFor(key: string, type: TaxonomicFilterGroupType, fallback: string): string {
    return getCoreFilterDefinition(key, type)?.label ?? fallback
}

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

type TaxonomicFilterEmptyStateProps = {
    isLoading?: boolean
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
                    {docsUrl ? (
                        <LemonButton
                            type="tertiary"
                            sideIcon={<IconOpenSidebar className="w-4 h-4" />}
                            to={`${docsUrl}?utm_medium=in-product&utm_campaign=taxonomic-filter-empty-state-docs-link`}
                            data-attr="product-introduction-docs-link"
                            targetBlank
                        >
                            Learn more
                        </LemonButton>
                    ) : null}
                </div>
            </div>
        </div>
    )
}

type Props = {
    groupType: TaxonomicFilterGroupType
    isLoading?: boolean
}

const DataWarehouseLoadingState = (): JSX.Element => {
    return (
        <div className="flex flex-col items-center p-8 mt-4 w-full text-center">
            <Spinner className="text-3xl" />
            <h2 className="mt-4 text-lg font-semibold">Loading data warehouse tables</h2>
            <p className="mt-2 text-sm text-secondary">
                This list will populate once your connected data warehouse tables have loaded.
            </p>
        </div>
    )
}

const DataWarehouseEmptyState = ({ isLoading = false }: { isLoading?: boolean }): JSX.Element => {
    if (isLoading) {
        return <DataWarehouseLoadingState />
    }

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

const RecentFiltersEmptyState = (): JSX.Element => {
    return (
        <div className="flex flex-col items-center p-8 mt-4 w-full text-center">
            <p className="text-sm text-secondary">No recent selections yet. Items you select will appear here.</p>
        </div>
    )
}

const PinnedFiltersEmptyState = (): JSX.Element => {
    const { searchQuery } = useValues(taxonomicFilterLogic)
    const hasSearch = searchQuery.trim().length > 0
    return (
        <div className="flex flex-col items-center p-8 mt-4 w-full text-center">
            <p className="text-sm text-secondary">
                {hasSearch
                    ? 'No pinned items match your search.'
                    : 'No pinned items yet. Hover over any item and click the pin icon to keep it handy here.'}
            </p>
        </div>
    )
}

const DescriptiveEmptyState = ({
    heading,
    explanation,
    hint,
}: {
    heading: string
    explanation: string
    hint: string
}): JSX.Element => {
    return (
        <div className="flex flex-col items-center gap-2 p-8 mt-4 w-full text-center">
            <p className="text-sm font-semibold text-primary">{heading}</p>
            <p className="text-sm text-secondary max-w-md">{explanation}</p>
            <p className="text-xs text-tertiary max-w-md">{hint}</p>
        </div>
    )
}

const PageviewUrlsEmptyState = (): JSX.Element => {
    const { hasPageview } = getProjectEventExistence()
    const pageviewLabel = labelFor('$pageview', TaxonomicFilterGroupType.Events, 'Pageview')
    const urlLabel = labelFor('$current_url', TaxonomicFilterGroupType.EventProperties, 'Current URL')
    return (
        <DescriptiveEmptyState
            heading={`${pageviewLabel} events filtered by ${urlLabel}`}
            explanation={`Pick a URL to match ${pageviewLabel} events whose ${urlLabel} equals it — a shortcut for "${pageviewLabel.toLowerCase()}s, but only on this page".`}
            hint={
                hasPageview
                    ? 'Type at least 3 characters to search URLs we have seen.'
                    : `No ${pageviewLabel} events have been ingested yet. Once your app sends them, URLs will appear here.`
            }
        />
    )
}

const PageviewEventsEmptyState = (): JSX.Element => {
    const { hasPageview } = getProjectEventExistence()
    const pageviewLabel = labelFor('$pageview', TaxonomicFilterGroupType.Events, 'Pageview')
    const urlLabel = labelFor('$current_url', TaxonomicFilterGroupType.EventProperties, 'Current URL')
    return (
        <DescriptiveEmptyState
            heading={`${pageviewLabel} events narrowed to one ${urlLabel}`}
            explanation={`Picking a URL creates a ${pageviewLabel} event already filtered to that ${urlLabel} — handy for series like "${pageviewLabel.toLowerCase()}s of /pricing".`}
            hint={
                hasPageview
                    ? 'Type at least 3 characters to search URLs we have seen.'
                    : `No ${pageviewLabel} events have been ingested yet. Once your app sends them, URLs will appear here.`
            }
        />
    )
}

const ScreensEmptyState = (): JSX.Element => {
    const { hasScreen } = getProjectEventExistence()
    const screenLabel = labelFor('$screen', TaxonomicFilterGroupType.Events, 'Screen')
    const screenNameLabel = labelFor('$screen_name', TaxonomicFilterGroupType.EventProperties, 'Screen name')
    return (
        <DescriptiveEmptyState
            heading={`${screenLabel} events filtered by ${screenNameLabel}`}
            explanation={`Pick a screen name to match ${screenLabel} events whose ${screenNameLabel} equals it — a shortcut for "${screenLabel.toLowerCase()}s, but only on this screen".`}
            hint={
                hasScreen
                    ? 'Type at least 3 characters to search screens we have seen.'
                    : `No ${screenLabel} events have been ingested yet. Once your app sends them, screen names will appear here.`
            }
        />
    )
}

const ScreenEventsEmptyState = (): JSX.Element => {
    const { hasScreen } = getProjectEventExistence()
    const screenLabel = labelFor('$screen', TaxonomicFilterGroupType.Events, 'Screen')
    const screenNameLabel = labelFor('$screen_name', TaxonomicFilterGroupType.EventProperties, 'Screen name')
    return (
        <DescriptiveEmptyState
            heading={`${screenLabel} events narrowed to one ${screenNameLabel}`}
            explanation={`Picking a screen name creates a ${screenLabel} event already filtered to that ${screenNameLabel} — handy for series like "views of Settings".`}
            hint={
                hasScreen
                    ? 'Type at least 3 characters to search screens we have seen.'
                    : `No ${screenLabel} events have been ingested yet. Once your app sends them, screen names will appear here.`
            }
        />
    )
}

const AutocaptureEventsEmptyState = (): JSX.Element => {
    const autocaptureLabel = labelFor('$autocapture', TaxonomicFilterGroupType.Events, 'Autocapture')
    const elementTextLabel = labelFor('$el_text', TaxonomicFilterGroupType.EventProperties, 'Element text')
    return (
        <DescriptiveEmptyState
            heading={`${autocaptureLabel} events narrowed to one ${elementTextLabel}`}
            explanation={`Picking an element creates an ${autocaptureLabel} event already filtered to that ${elementTextLabel.toLowerCase()} — handy for series like "clicks of Sign up".`}
            hint="Type at least 3 characters to search element text we have seen."
        />
    )
}

const EmailAddressesEmptyState = (): JSX.Element => {
    const emailLabel = labelFor('email', TaxonomicFilterGroupType.PersonProperties, 'Email address')
    return (
        <DescriptiveEmptyState
            heading={`Persons filtered by ${emailLabel.toLowerCase()}`}
            explanation={`Pick an email to match events by the person whose ${emailLabel.toLowerCase()} equals it — a shortcut for "events, but only by this person".`}
            hint="Type at least 5 characters to search emails we have seen on person properties."
        />
    )
}

const DefaultEmptyState = (): JSX.Element | null => {
    return null
}

const EMPTY_STATES: Partial<Record<TaxonomicFilterGroupType, React.ComponentType<TaxonomicFilterEmptyStateProps>>> = {
    [TaxonomicFilterGroupType.DataWarehouse]: DataWarehouseEmptyState,
    [TaxonomicFilterGroupType.DataWarehouseProperties]: DataWarehouseEmptyState,
    [TaxonomicFilterGroupType.DataWarehousePersonProperties]: DataWarehouseEmptyState,
    [TaxonomicFilterGroupType.RecentFilters]: RecentFiltersEmptyState,
    [TaxonomicFilterGroupType.PinnedFilters]: PinnedFiltersEmptyState,
    [TaxonomicFilterGroupType.PageviewUrls]: PageviewUrlsEmptyState,
    [TaxonomicFilterGroupType.PageviewEvents]: PageviewEventsEmptyState,
    [TaxonomicFilterGroupType.Screens]: ScreensEmptyState,
    [TaxonomicFilterGroupType.ScreenEvents]: ScreenEventsEmptyState,
    [TaxonomicFilterGroupType.AutocaptureEvents]: AutocaptureEventsEmptyState,
    [TaxonomicFilterGroupType.EmailAddresses]: EmailAddressesEmptyState,
} as const

export const taxonomicFilterGroupTypesWithEmptyStates = Object.keys(EMPTY_STATES) as TaxonomicFilterGroupType[]

export const TaxonomicFilterEmptyState = ({ groupType, isLoading = false }: Props): JSX.Element => {
    const EmptyState = EMPTY_STATES[groupType]

    if (EmptyState) {
        return <EmptyState isLoading={isLoading} />
    }

    return <DefaultEmptyState />
}
