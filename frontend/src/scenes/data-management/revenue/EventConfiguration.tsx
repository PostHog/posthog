import { IconInfo, IconTrash } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { RevenueTrackingEventItem } from '~/queries/schema/schema-general'

import { CurrencyDropdown } from './CurrencyDropdown'
import { revenueEventsSettingsLogic } from './revenueEventsSettingsLogic'

export function EventConfiguration({ buttonRef }: { buttonRef: React.RefObject<HTMLButtonElement> }): JSX.Element {
    const { events, saveEventsDisabledReason, changesMadeToEvents } = useValues(revenueEventsSettingsLogic)
    const { addEvent, deleteEvent, updateEventRevenueProperty, updateEventRevenueCurrencyProperty, save } =
        useActions(revenueEventsSettingsLogic)

    return (
        <div>
            <h3 className="mb-2">Event Configuration</h3>
            <LemonTable<RevenueTrackingEventItem>
                columns={[
                    { key: 'eventName', title: 'Event name', dataIndex: 'eventName' },
                    {
                        key: 'revenueProperty',
                        title: 'Revenue property',
                        dataIndex: 'revenueProperty',
                        render: (_, item: RevenueTrackingEventItem) => {
                            return (
                                <TaxonomicPopover
                                    showNumericalPropsOnly
                                    size="small"
                                    className="my-1"
                                    groupType={TaxonomicFilterGroupType.EventProperties}
                                    onChange={(newPropertyName) =>
                                        updateEventRevenueProperty(item.eventName, newPropertyName)
                                    }
                                    value={item.revenueProperty}
                                    placeholder="Choose event property"
                                    disabledReason={
                                        item.eventName === '$pageview' || item.eventName === '$autocapture'
                                            ? 'Built-in events must use revenue'
                                            : undefined
                                    }
                                />
                            )
                        },
                    },
                    {
                        key: 'revenueCurrencyProperty',
                        title: (
                            <span>
                                Revenue currency property
                                <Tooltip title="The currency of the revenue event. You can choose between a property on your event OR a hardcoded currency.">
                                    <IconInfo className="ml-1" />
                                </Tooltip>
                            </span>
                        ),
                        dataIndex: 'revenueCurrencyProperty',
                        render: (_, item: RevenueTrackingEventItem) => {
                            return (
                                <div className="flex flex-col w-full gap-3 my-1 min-w-[250px] whitespace-nowrap">
                                    <div className="flex flex-row gap-1">
                                        <span className="font-bold">Dynamic property: </span>
                                        <TaxonomicPopover
                                            size="small"
                                            groupType={TaxonomicFilterGroupType.EventProperties}
                                            onChange={(newPropertyName) =>
                                                updateEventRevenueCurrencyProperty(item.eventName, {
                                                    property: newPropertyName!,
                                                })
                                            }
                                            value={item.revenueCurrencyProperty.property ?? null}
                                            placeholder="Choose event property"
                                        />
                                    </div>
                                    <div className="flex flex-row gap-1">
                                        or <span className="font-bold">Static currency: </span>
                                        <CurrencyDropdown
                                            size="small"
                                            onChange={(currency) =>
                                                updateEventRevenueCurrencyProperty(item.eventName, {
                                                    static: currency!,
                                                })
                                            }
                                            value={item.revenueCurrencyProperty.static ?? null}
                                        />
                                    </div>
                                </div>
                            )
                        },
                    },
                    {
                        key: 'delete',
                        fullWidth: true,
                        title: (
                            <div className="flex flex-col gap-1 items-end w-full">
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

                                    <LemonButton
                                        type="primary"
                                        onClick={save}
                                        disabledReason={saveEventsDisabledReason}
                                    >
                                        Save
                                    </LemonButton>
                                </div>
                                {changesMadeToEvents && (
                                    <span className="text-xs text-error normal-case font-normal">
                                        Remember to save your changes to take effect
                                    </span>
                                )}
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
    )
}
