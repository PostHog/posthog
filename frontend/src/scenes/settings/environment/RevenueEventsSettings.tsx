import { IconTrash } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { useCallback } from 'react'
import { revenueEventsSettingsLogic } from 'scenes/settings/environment/revenueEventsSettingsLogic'

import { RevenueTrackingEventItem } from '~/queries/schema'

export function RevenueEventsSettings(): JSX.Element {
    const { saveDisabledReason, events } = useValues(revenueEventsSettingsLogic)
    const { addEvent, deleteEvent, updatePropertyName, save } = useActions(revenueEventsSettingsLogic)

    const renderPropertyColumn = useCallback(
        (_, item: RevenueTrackingEventItem) => {
            return (
                <TaxonomicPopover
                    groupType={TaxonomicFilterGroupType.EventProperties}
                    onChange={(newPropertyName) => updatePropertyName(item.eventName, newPropertyName)}
                    value={item.revenueProperty}
                    placeholder="Choose event property"
                    excludedProperties={{}}
                    showNumericalPropsOnly={true}
                    disabledReason={
                        item.eventName === '$pageview' || item.eventName === '$autocapture'
                            ? 'Built-in events must use revenue'
                            : undefined
                    }
                />
            )
        },
        [updatePropertyName]
    )

    return (
        <div className="space-y-4">
            <div>
                <p>Add revenue tracking for Custom events in Web analytics</p>
            </div>
            <LemonTable<RevenueTrackingEventItem>
                columns={[
                    { key: 'eventName', title: 'Event name', dataIndex: 'eventName' },
                    {
                        key: 'revenueProperty',
                        title: 'Revenue property',
                        dataIndex: 'revenueProperty',
                        render: renderPropertyColumn,
                    },
                    {
                        key: 'delete',
                        title: '',
                        render: (_, item) => (
                            <LemonButton
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

            <TaxonomicPopover
                groupType={TaxonomicFilterGroupType.CustomEvents}
                onChange={addEvent}
                value={undefined}
                placeholder="Choose custom events to add"
                excludedProperties={{
                    [TaxonomicFilterGroupType.CustomEvents]: [null, ...events.map((item) => item.eventName)],
                }}
            />
            <div className="mt-4">
                <LemonButton type="primary" onClick={save} disabledReason={saveDisabledReason}>
                    Save
                </LemonButton>
            </div>
        </div>
    )
}
