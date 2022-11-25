import { EventType, PropertyFilterType } from '~/types'
import { autoCaptureEventToDescription } from 'lib/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { Link } from 'lib/components/Link'
import { TZLabel } from 'lib/components/TZLabel'
import { Property } from 'lib/components/Property'
import { urls } from 'scenes/urls'
import { PersonHeader } from 'scenes/persons/PersonHeader'

export function renderColumn(type: PropertyFilterType, key: string, record: EventType): JSX.Element | string {
    if (type === PropertyFilterType.Meta) {
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
        } else {
            return String(record[key])
        }
    } else if (type === PropertyFilterType.Event) {
        return <Property value={record.properties[key]} />
    } else if (type === PropertyFilterType.Person) {
        if (key === '') {
            return (
                <Link to={urls.person(record.distinct_id)}>
                    <PersonHeader noLink withIcon person={record.person} />
                </Link>
            )
        } else {
            return <Property value={record.person?.properties[key]} />
        }
    }
    return <div>Unknown</div>
}
