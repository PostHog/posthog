import { PropertyFilterType } from '~/types'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'

export function renderTitle(key: string): JSX.Element | string {
    if (key === 'timestamp') {
        return 'Time'
    } else if (key === 'event') {
        return 'Event'
    } else if (key === 'person') {
        return 'Person'
    } else if (key === 'url') {
        return 'URL / Screen'
    } else if (key.startsWith('properties.')) {
        return <PropertyKeyInfo value={key.substring(11)} type={PropertyFilterType.Event} disableIcon />
    } else if (key.startsWith('person.properties.')) {
        // NOTE: PropertyFilterType.Event is not a mistake. PropertyKeyInfo only knows events vs elements ¯\_(ツ)_/¯
        return <PropertyKeyInfo value={key.substring(18)} type={PropertyFilterType.Event} disableIcon />
    } else {
        return String(key)
    }
}
