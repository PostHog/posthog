import { PropertyFilterType } from '~/types'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'

export function renderTitle(type: PropertyFilterType, key: string): JSX.Element | string {
    if (type === PropertyFilterType.Meta) {
        if (key === 'timestamp') {
            return 'Time'
        }
        return key
    } else if (type === PropertyFilterType.Event || type === PropertyFilterType.Element) {
        return <PropertyKeyInfo value={key} type={type} disableIcon />
    } else if (type === PropertyFilterType.Person) {
        if (key === '') {
            return 'Person'
        } else {
            return <PropertyKeyInfo value={key} type="event" disableIcon />
        }
    } else {
        return String(type)
    }
}
