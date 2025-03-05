import { IconInfo, IconTrash } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { useCallback, useRef } from 'react'
import { revenueEventsSettingsLogic } from 'scenes/data-management/revenue/revenueEventsSettingsLogic'

import { QueryFeature } from '~/queries/nodes/DataTable/queryFeatures'
import { Query } from '~/queries/Query/Query'
import { RevenueTrackingEventItem, SupportedCurrencies } from '~/queries/schema/schema-general'

import { CurrencyDropdown } from './CurrencyDropdown'

export function RevenueEventsSettings(): JSX.Element {
    const { saveDisabledReason, events, baseCurrency, eventsQuery } = useValues(revenueEventsSettingsLogic)
    const { addEvent, deleteEvent, updatePropertyName, updateCurrencyPropertyName, updateBaseCurrency, save } =
        useActions(revenueEventsSettingsLogic)

    const renderPropertyColumn = useCallback(
        (
                key: keyof RevenueTrackingEventItem,
                updatePropertyFunction: (eventName: string, propertyName: string) => void
            ) =>
            // eslint-disable-next-line react/display-name
            (_, item: RevenueTrackingEventItem) => {
                return (
                    <TaxonomicPopover
                        size="small"
                        className="my-1"
                        groupType={TaxonomicFilterGroupType.EventProperties}
                        onChange={(newPropertyName) => updatePropertyFunction(item.eventName, newPropertyName)}
                        value={item[key]}
                        placeholder="Choose event property"
                        showNumericalPropsOnly={true}
                        disabledReason={
                            item.eventName === '$pageview' || item.eventName === '$autocapture'
                                ? 'Built-in events must use revenue'
                                : undefined
                        }
                    />
                )
            },
        []
    )

    const buttonRef = useRef<HTMLButtonElement | null>(null)

    return (
        <div className="flex flex-col gap-8">
            <div>
                <h3>Base currency</h3>
                <p>
                    Posthog will convert all revenue values to this currency before displaying them to you. This is set
                    to USD (American Dollar) by default.
                </p>
                <CurrencyDropdown
                    value={baseCurrency}
                    onChange={(currency) => {
                        updateBaseCurrency(currency as SupportedCurrencies)
                        save()
                    }}
                />
            </div>

            <div>
                <h3 className="mb-2">Event Configuration</h3>
                <ProductIntroduction
                    productName="Revenue tracking"
                    thingName="revenue event"
                    description="Revenue events are used to track revenue in Web analytics. You can choose which custom events PostHog should consider as revenue events, and which event property corresponds to the value of the event."
                    isEmpty={events.length === 0}
                    action={() => buttonRef.current?.click()}
                />
                <LemonTable<RevenueTrackingEventItem>
                    columns={[
                        { key: 'eventName', title: 'Event name', dataIndex: 'eventName' },
                        {
                            key: 'revenueProperty',
                            title: 'Revenue property',
                            dataIndex: 'revenueProperty',
                            render: renderPropertyColumn('revenueProperty', updatePropertyName),
                        },
                        {
                            key: 'revenueCurrencyProperty',
                            title: (
                                <span>
                                    Revenue currency property
                                    <Tooltip title="The currency of the revenue event. If not set, the account's default currency will be used. We'll soon convert revenue data from this currency to your base currency for reporting purposes.">
                                        <IconInfo className="ml-1" />
                                    </Tooltip>
                                </span>
                            ),
                            dataIndex: 'revenueCurrencyProperty',
                            render: renderPropertyColumn('revenueCurrencyProperty', updateCurrencyPropertyName),
                        },
                        {
                            key: 'delete',
                            fullWidth: true,
                            title: (
                                <div className="flex flex-row w-full gap-1 justify-end my-2">
                                    <TaxonomicPopover
                                        type="primary"
                                        groupType={TaxonomicFilterGroupType.CustomEvents}
                                        onChange={addEvent}
                                        value={undefined}
                                        placeholder="Create revenue event"
                                        placeholderClass=""
                                        excludedProperties={{
                                            [TaxonomicFilterGroupType.CustomEvents]: [
                                                null,
                                                ...events.map((item) => item.eventName),
                                            ],
                                        }}
                                        id="data-management-revenue-settings-add-event"
                                        ref={buttonRef}
                                    />

                                    <LemonButton type="primary" onClick={save} disabledReason={saveDisabledReason}>
                                        Save
                                    </LemonButton>
                                </div>
                            ),
                            render: (_, item) => (
                                <LemonButton
                                    className="float-right"
                                    size="small"
                                    type="secondary"
                                    onClick={() => deleteEvent(item.eventName)}
                                    icon={<IconTrash />}
                                >
                                    Delete
                                </LemonButton>
                            ),
                        },
                    ]}
                    dataSource={events}
                    rowKey={(item) => item.eventName}
                />
            </div>

            {eventsQuery ? (
                <div>
                    <h3>Revenue events</h3>
                    <p>
                        The following revenue events are available in your data. This is helpful when you're trying to
                        debug what your revenue events look like.
                    </p>
                    <Query
                        query={eventsQuery}
                        context={{
                            showOpenEditorButton: true,
                            extraDataTableQueryFeatures: [QueryFeature.highlightExceptionEventRows],
                        }}
                    />
                </div>
            ) : null}
        </div>
    )
}
