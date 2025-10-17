import { HogFunctionTypeType } from '~/types'

export function humanizeHogFunctionType(type: HogFunctionTypeType, plural: boolean = false): string {
    if (type === 'source_webhook') {
        return 'source' + (plural ? 's' : '')
    }
    return type.replaceAll('_', ' ') + (plural ? 's' : '')
}
