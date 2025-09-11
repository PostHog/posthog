import { HogFunctionTypeType } from '~/types'

export function humanizeHogFunctionType(type: HogFunctionTypeType): string {
    if (type === 'source_webhook') {
        return 'source'
    }
    return type.replaceAll('_', ' ')
}
