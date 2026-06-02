import {
    ActivityChange,
    ActivityLogItem,
    HumanizedChange,
    defaultDescriber,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { SentenceList } from 'lib/components/ActivityLog/SentenceList'

// Mirrors backend `sync_frequency_to_sync_frequency_interval` in
// products/data_warehouse/backend/models/external_data_schema.py — the values arrive
// as `str(timedelta(...))` ("H:MM:SS" or "X day(s), H:MM:SS"). Falls through to the raw
// string for any unmapped interval, so the UI degrades gracefully if a new bucket lands
// on the backend before this map is updated.
function humanizeInterval(raw: string | null | undefined): string {
    if (!raw) {
        return 'none'
    }
    const buckets: Record<string, string> = {
        '0:01:00': '1 minute',
        '0:05:00': '5 minutes',
        '0:15:00': '15 minutes',
        '0:30:00': '30 minutes',
        '1:00:00': '1 hour',
        '6:00:00': '6 hours',
        '12:00:00': '12 hours',
        '1 day, 0:00:00': '1 day',
        '7 days, 0:00:00': '7 days',
        '30 days, 0:00:00': '30 days',
    }
    return buckets[raw] ?? raw
}

function describeChange(change: ActivityChange): JSX.Element | null {
    if (change.field === 'sync_frequency_interval') {
        const before = humanizeInterval(change.before as string | null)
        const after = humanizeInterval(change.after as string | null)
        return (
            <>
                changed sync frequency from <strong>{before}</strong> to <strong>{after}</strong>
            </>
        )
    }
    if (change.field === 'is_materialized') {
        return <>{change.after ? <>enabled materialization</> : <>disabled materialization</>}</>
    }
    if (change.field === 'query') {
        return <>updated the query</>
    }
    return <>changed {change.field}</>
}

export function dataWarehouseSavedQueryActivityDescriber(
    logItem: ActivityLogItem,
    asNotification?: boolean
): HumanizedChange {
    if (logItem.scope !== 'DataWarehouseSavedQuery') {
        console.error('data warehouse saved query describer received a non-data warehouse saved query activity')
        return { description: null }
    }

    const user = <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong>
    const viewName = logItem.detail?.name ? <strong>{logItem.detail.name}</strong> : <i>a view</i>

    if (logItem.activity === 'created') {
        return {
            description: <SentenceList listParts={[<>created {viewName}</>]} prefix={user} />,
        }
    }

    if (logItem.activity === 'updated') {
        const changes = logItem.detail?.changes ?? []
        const parts = changes.map(describeChange).filter((p): p is JSX.Element => p !== null)
        return {
            description: (
                <SentenceList
                    listParts={parts.length > 0 ? parts : [<>updated the view</>]}
                    prefix={user}
                    suffix={<>on {viewName}</>}
                />
            ),
        }
    }

    if (logItem.activity === 'sync_triggered') {
        return {
            description: <SentenceList listParts={[<>triggered an ad-hoc sync on {viewName}</>]} prefix={user} />,
        }
    }

    if (logItem.activity === 'sync_cancelled') {
        return {
            description: <SentenceList listParts={[<>cancelled a running sync on {viewName}</>]} prefix={user} />,
        }
    }

    if (logItem.activity === 'materialization_enabled') {
        const changes = logItem.detail?.changes ?? []
        const freqChange = changes.find((c) => c.field === 'sync_frequency_interval')
        const parts: JSX.Element[] = [<>enabled materialization for {viewName}</>]
        if (freqChange) {
            const after = humanizeInterval(freqChange.after as string | null)
            parts.push(
                <>
                    with sync frequency <strong>{after}</strong>
                </>
            )
        }
        return { description: <SentenceList listParts={parts} prefix={user} /> }
    }

    if (logItem.activity === 'materialization_disabled') {
        return {
            description: <SentenceList listParts={[<>disabled materialization for {viewName}</>]} prefix={user} />,
        }
    }

    if (logItem.activity === 'sync_frequency_reset') {
        const changes = logItem.detail?.changes ?? []
        const freqChange = changes.find((c) => c.field === 'sync_frequency_interval')
        const after = freqChange ? humanizeInterval(freqChange.after as string | null) : 'default'
        return {
            description: (
                <SentenceList
                    listParts={[
                        <>
                            auto-reset sync frequency to <strong>{after}</strong> for {viewName}
                        </>,
                    ]}
                    prefix={user}
                />
            ),
        }
    }

    if (logItem.activity === 'deleted') {
        return {
            description: <SentenceList listParts={[<>deleted {viewName}</>]} prefix={user} />,
        }
    }

    return defaultDescriber(logItem, asNotification, viewName)
}
