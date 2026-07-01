import { useValues } from 'kea'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'

import { actionsModel } from '~/models/actionsModel'
import { EventsQuery, SessionsQuery } from '~/queries/schema/schema-general'

interface EventNameProps {
    query: EventsQuery | SessionsQuery
    setQuery?: (query: EventsQuery | SessionsQuery) => void
}

/** Single picker for filtering events by event name or by a saved action (mutually exclusive, like insights). */
export function EventName({ query, setQuery }: EventNameProps): JSX.Element {
    const { actionsById } = useValues(actionsModel)

    const actionId = query.actionId || null
    const value = actionId != null ? actionId : (query.event ?? null)

    return (
        <TaxonomicPopover
            groupType={actionId != null ? TaxonomicFilterGroupType.Actions : TaxonomicFilterGroupType.Events}
            groupTypes={[
                TaxonomicFilterGroupType.SuggestedFilters,
                TaxonomicFilterGroupType.Events,
                TaxonomicFilterGroupType.Actions,
            ]}
            value={value}
            onChange={(newValue, groupType) => {
                if (!setQuery) {
                    return
                }
                // The clear affordance emits an empty string, so treat empty/nullish as "no filter".
                const cleared = newValue == null || newValue === ''
                if (cleared) {
                    setQuery({ ...query, event: null, actionId: undefined })
                } else if (groupType === TaxonomicFilterGroupType.Actions) {
                    setQuery({ ...query, event: null, actionId: Number(newValue) })
                } else {
                    setQuery({ ...query, actionId: undefined, event: String(newValue) })
                }
            }}
            renderValue={(v) =>
                actionId != null ? (
                    <>{actionsById[actionId]?.name || `Action #${actionId}`}</>
                ) : v != null ? (
                    <PropertyKeyInfo value={String(v)} disablePopover type={TaxonomicFilterGroupType.Events} />
                ) : null
            }
            disabled={!setQuery}
            allowClear
            excludedProperties={{ [TaxonomicFilterGroupType.Events]: [null] }}
            size="small"
            type="secondary"
            placeholder="Select an event"
            data-attr="event-name-box"
            selectingKeyOnly
        />
    )
}
