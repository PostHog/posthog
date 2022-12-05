import { PropertyFilterType } from '~/types'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { QueryCustom } from '~/queries/schema'

export function renderTitle(key: string, custom?: QueryCustom): JSX.Element | string {
    if (key === 'timestamp') {
        return 'Time'
    } else if (key === 'created_at') {
        return 'First seen'
    } else if (key === 'event') {
        return 'Event'
    } else if (key === 'person') {
        return 'Person'
    } else if (key === 'url') {
        return 'URL / Screen'
    } else if (key.startsWith('properties.')) {
        return <PropertyKeyInfo value={key.substring(11)} type={PropertyFilterType.Event} disableIcon />
    } else if (key.startsWith('custom.')) {
        return custom?.[key.substring(7)]?.title ?? key.substring(7).replace('_', ' ')
    } else if (key.startsWith('person.properties.')) {
        // NOTE: type=Event is not a mistake, even if it's a person property. Don't ask, won't fix.
        return <PropertyKeyInfo value={key.substring(18)} type={PropertyFilterType.Event} disableIcon />
    } else {
        return String(key)
    }
}
