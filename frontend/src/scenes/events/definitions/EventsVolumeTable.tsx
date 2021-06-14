import React from 'react'
import { useValues } from 'kea'
import { Alert, Skeleton } from 'antd'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { PageHeader } from 'lib/components/PageHeader'
import { UsageDisabledWarning, VolumeTable } from './VolumeTable'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'

export function EventsVolumeTable(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { eventDefinitions, loaded } = useValues(eventDefinitionsModel)

    return (
        <>
            <PageHeader
                title="Events Stats"
                caption="See all event names that have ever been sent to this team, including the volume and how often queries where made using this event."
                style={{ marginTop: 0 }}
            />
            {loaded ? (
                <>
                    {preflight && !preflight?.is_event_property_usage_enabled ? (
                        <UsageDisabledWarning tab="Events Stats" />
                    ) : (
                        eventDefinitions[0].volume_30_day === null && (
                            <>
                                <Alert
                                    type="warning"
                                    message="We haven't been able to get usage and volume data yet. Please check later."
                                />
                            </>
                        )
                    )}
                    <VolumeTable data={eventDefinitions} type="event" />
                </>
            ) : (
                <Skeleton active paragraph={{ rows: 5 }} />
            )}
        </>
    )
}
