import { IconInfo, IconTrash } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useCallback } from 'react'

import { RevenueTrackingEventItem } from '~/queries/schema/schema-general'

import { revenueEventsSettingsLogic } from './revenueEventsSettingsLogic'

export function EventConfiguration({ buttonRef }: { buttonRef: React.RefObject<HTMLButtonElement> }): JSX.Element {
    const { events, saveDisabledReason } = useValues(revenueEventsSettingsLogic)
    const { addEvent, deleteEvent, updateEventRevenueProperty, updateEventRevenueCurrencyProperty, save } =
        useActions(revenueEventsSettingsLogic)

    const renderPropertyColumn = useCallback(
        (
                key: keyof RevenueTrackingEventItem,
                updatePropertyFunction: (eventName: string, propertyName: string) => void
            ) =>
            // eslint-disable-next-line react/display-name
            (_: string | undefined, item: RevenueTrackingEventItem) => {
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
                        render: renderPropertyColumn('revenueProperty', updateEventRevenueProperty),
                    },
                    {
                        key: 'revenueCurrencyProperty',
                        title: (
                            <span>
                                Revenue currency property
                                <Tooltip title="The currency of the revenue event. If not set, the account's default currency will be used.">
                                    <IconInfo className="ml-1" />
                                </Tooltip>
                            </span>
                        ),
                        dataIndex: 'revenueCurrencyProperty',
                        render: renderPropertyColumn('revenueCurrencyProperty', updateEventRevenueCurrencyProperty),
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
    )
}
