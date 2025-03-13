import { IconPlus } from '@posthog/icons'
import { LemonTabs } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useRef, useState } from 'react'

import { BaseCurrency } from './BaseCurrency'
import { EventConfiguration } from './EventConfiguration'
import { ExternalTableConfiguration } from './ExternalTableConfiguration'
import { revenueEventsSettingsLogic } from './revenueEventsSettingsLogic'
import { RevenueExampleEventsTable } from './RevenueExampleEventsTable'
import { RevenueExampleExternalTablesData } from './RevenueExampleExternalTablesData'

type Tab = 'events' | 'external-tables'

export function RevenueEventsSettings(): JSX.Element {
    const [activeTab, setActiveTab] = useState<Tab>('events')

    const { events, externalDataSchemas } = useValues(revenueEventsSettingsLogic)

    const { featureFlags } = useValues(featureFlagLogic)

    const eventsButtonRef = useRef<HTMLButtonElement>(null)
    const externalDataSchemasButtonRef = useRef<HTMLButtonElement>(null)

    let introductionDescription =
        'Revenue events are used to track revenue in Web analytics. You can choose which custom events PostHog should consider as revenue events, and which event property corresponds to the value of the event.'
    if (featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_DATA_WAREHOUSE_REVENUE_SETTINGS]) {
        introductionDescription +=
            " You can also import revenue data from external tables if you're using our Data Warehouse."
    }

    return (
        <div className="flex flex-col gap-8">
            <ProductIntroduction
                productName="Revenue tracking"
                thingName="revenue event"
                description={introductionDescription}
                isEmpty={events.length === 0 && externalDataSchemas.length === 0}
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
                                Create revenue event
                            </LemonButton>

                            {featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_DATA_WAREHOUSE_REVENUE_SETTINGS] && (
                                <LemonButton
                                    type="primary"
                                    icon={<IconPlus />}
                                    onClick={() => {
                                        externalDataSchemasButtonRef.current?.scrollIntoView({ behavior: 'smooth' })
                                        externalDataSchemasButtonRef.current?.click()
                                    }}
                                    data-attr="import-revenue-external-data-schema"
                                >
                                    Import revenue data from external tables
                                </LemonButton>
                            )}
                        </div>
                    </>
                }
            />

            <BaseCurrency />

            <EventConfiguration buttonRef={eventsButtonRef} />

            {featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_DATA_WAREHOUSE_REVENUE_SETTINGS] && (
                <ExternalTableConfiguration buttonRef={externalDataSchemasButtonRef} />
            )}

            {featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_DATA_WAREHOUSE_REVENUE_SETTINGS] ? (
                <LemonTabs
                    activeKey={activeTab}
                    onChange={(key) => setActiveTab(key as Tab)}
                    tabs={[
                        {
                            key: 'events',
                            label: 'Revenue events',
                            content: <RevenueExampleEventsTable />,
                        },
                        {
                            key: 'external-tables',
                            label: 'External tables',
                            content: <RevenueExampleExternalTablesData />,
                        },
                    ]}
                />
            ) : (
                <RevenueExampleEventsTable />
            )}
        </div>
    )
}
