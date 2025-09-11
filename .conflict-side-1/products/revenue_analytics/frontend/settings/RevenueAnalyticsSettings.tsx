import { useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonTabs, Link } from '@posthog/lemon-ui'

import { BaseCurrency } from 'lib/components/BaseCurrency/BaseCurrency'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { EventConfiguration } from './EventConfiguration'
import { ExternalDataSourceConfiguration } from './ExternalDataSourceConfiguration'
import { FilterTestAccountsConfiguration } from './FilterTestAccountsConfiguration'
import { GoalsConfiguration } from './GoalsConfiguration'
import { RevenueExampleDataWarehouseTablesData } from './RevenueExampleDataWarehouseTablesData'
import { RevenueExampleEventsTable } from './RevenueExampleEventsTable'
import { revenueAnalyticsSettingsLogic } from './revenueAnalyticsSettingsLogic'

type Tab = 'events' | 'data-warehouse'

export function RevenueAnalyticsSettings(): JSX.Element {
    const [activeTab, setActiveTab] = useState<Tab>('events')

    const { events } = useValues(revenueAnalyticsSettingsLogic)
    const { dataWarehouseSources, dataWarehouseSourcesLoading } = useValues(dataWarehouseSettingsLogic)

    const { featureFlags } = useValues(featureFlagLogic)

    const eventsButtonRef = useRef<HTMLButtonElement>(null)
    const dataWarehouseTablesButtonRef = useRef<HTMLButtonElement>(null)

    const product = featureFlags[FEATURE_FLAGS.REVENUE_ANALYTICS] ? 'Revenue analytics' : 'Web analytics'

    let introductionDescription = `Revenue events are used to track revenue in ${product}. You can choose which custom events PostHog should consider as revenue events, and which event property corresponds to the value of the event.`
    if (featureFlags[FEATURE_FLAGS.REVENUE_ANALYTICS]) {
        introductionDescription += ' You can also import revenue data from your PostHog data warehouse tables.'
    }

    const hasNoEvents = !events.length
    const hasNoDataWarehouseSources =
        !dataWarehouseSourcesLoading &&
        !dataWarehouseSources?.results.filter((source) => source.source_type === 'Stripe').length

    return (
        <SceneContent forceNewSpacing>
            <SceneTitleSection
                name="Revenue"
                description={introductionDescription}
                resourceType={{
                    type: 'revenue_analytics',
                }}
            />
            <SceneDivider />
            <ProductIntroduction
                productName="Revenue tracking"
                thingName="revenue source"
                description={introductionDescription}
                isEmpty={hasNoEvents && hasNoDataWarehouseSources}
                actionElementOverride={
                    <>
                        <div className="flex flex-col gap-2">
                            <LemonButton
                                type="primary"
                                icon={<IconPlus />}
                                onClick={() => {
                                    eventsButtonRef.current?.scrollIntoView({ behavior: 'smooth' })
                                    eventsButtonRef.current?.click()
                                }}
                                data-attr="create-revenue-event"
                            >
                                Add revenue event
                            </LemonButton>

                            {featureFlags[FEATURE_FLAGS.REVENUE_ANALYTICS] && (
                                <>
                                    <LemonButton
                                        type="primary"
                                        icon={<IconPlus />}
                                        onClick={() => {
                                            dataWarehouseTablesButtonRef.current?.scrollIntoView({ behavior: 'smooth' })
                                            dataWarehouseTablesButtonRef.current?.click()
                                        }}
                                        data-attr="import-revenue-data-warehouse-tables"
                                    >
                                        Import revenue data from data warehouse
                                    </LemonButton>
                                    <span className="text-xs text-muted-alt">
                                        Only Stripe is supported currently. <br />
                                        <Link to="https://github.com/PostHog/posthog/issues/new?assignees=&labels=enhancement,feature/revenue-analytics%2C+feature&projects=&template=feature_request.yml&title=New%20revenue%20source:%20%3Cinsert%20source%3E">
                                            Request more revenue integrations.
                                        </Link>
                                    </span>
                                </>
                            )}
                        </div>
                    </>
                }
            />

            <BaseCurrency />
            <SceneDivider />
            <FilterTestAccountsConfiguration />
            <SceneDivider />

            {featureFlags[FEATURE_FLAGS.REVENUE_ANALYTICS] && <GoalsConfiguration />}
            <SceneDivider />
            {featureFlags[FEATURE_FLAGS.REVENUE_ANALYTICS] && (
                <>
                    <ExternalDataSourceConfiguration buttonRef={dataWarehouseTablesButtonRef} />
                    <SceneDivider />
                </>
            )}
            <EventConfiguration buttonRef={eventsButtonRef} />
            <SceneDivider />
            {featureFlags[FEATURE_FLAGS.REVENUE_ANALYTICS] ? (
                <LemonTabs
                    activeKey={activeTab}
                    onChange={(key) => setActiveTab(key as Tab)}
                    tabs={[
                        {
                            key: 'data-warehouse',
                            label: 'Data Warehouse revenue events',
                            content: <RevenueExampleDataWarehouseTablesData />,
                        },
                        {
                            key: 'events',
                            label: 'Revenue events',
                            content: <RevenueExampleEventsTable />,
                        },
                    ]}
                />
            ) : (
                <RevenueExampleEventsTable />
            )}
        </SceneContent>
    )
}
