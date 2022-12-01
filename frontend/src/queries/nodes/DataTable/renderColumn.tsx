import { EventType } from '~/types'
import { autoCaptureEventToDescription } from 'lib/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { Link } from 'lib/components/Link'
import { TZLabel } from 'lib/components/TZLabel'
import { Property } from 'lib/components/Property'
import { urls } from 'scenes/urls'
import { PersonHeader } from 'scenes/persons/PersonHeader'

export function renderColumn(key: string, record: EventType): JSX.Element | string {
    if (key === 'event') {
        if (record.event === '$autocapture') {
            return autoCaptureEventToDescription(record)
        } else {
            const content = <PropertyKeyInfo value={record.event} type="event" />
            const url = record.properties.$sentry_url
            return url ? (
                <Link to={url} target="_blank">
                    {content}
                </Link>
            ) : (
                content
            )
        }
    } else if (key === 'timestamp') {
        return <TZLabel time={record.timestamp} showSeconds />
    } else if (key.startsWith('properties.')) {
        return <Property value={record.properties[key.substring(11)]} />
    } else if (key.startsWith('person.properties.')) {
        return <Property value={record.person?.properties?.[key.substring(18)]} />
    } else if (key === 'person') {
        return (
            <Link to={urls.person(record.distinct_id)}>
                <PersonHeader noLink withIcon person={record.person} />
            </Link>
        )
    } else {
        return String(record[key])
    }
}
