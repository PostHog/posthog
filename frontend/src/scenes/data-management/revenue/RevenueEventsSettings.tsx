import { IconTrash } from '@posthog/icons'
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
import { RevenueTrackingEventItem } from '~/queries/schema/schema-general'

const ADD_EVENT_BUTTON_ID = 'data-management-revenue-settings-add-event'

export function RevenueEventsSettings(): JSX.Element {
    const { saveDisabledReason, events, eventsQuery } = useValues(revenueEventsSettingsLogic)
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

    const buttonRef = useRef<HTMLButtonElement | null>(null)

    return (
        <div className="space-y-4">
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
                type="primary"
                groupType={TaxonomicFilterGroupType.CustomEvents}
                onChange={addEvent}
                value={undefined}
                placeholder="Create revenue event"
                placeholderClass=""
                excludedProperties={{
                    [TaxonomicFilterGroupType.CustomEvents]: [null, ...events.map((item) => item.eventName)],
                }}
                id={ADD_EVENT_BUTTON_ID}
                ref={buttonRef}
            />
            <div className="mt-4">
                <LemonButton type="primary" onClick={save} disabledReason={saveDisabledReason}>
                    Save
                </LemonButton>
            </div>

            <Query
                query={eventsQuery}
                context={{
                    showOpenEditorButton: true,
                    extraDataTableQueryFeatures: [QueryFeature.highlightExceptionEventRows],
                }}
            />
        </div>
    )
}
