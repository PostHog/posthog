import { HogFunctionTypeType } from '~/types'

export type HogFunctionDeliveryType = 'batch' | 'realtime'

// Batch exports vs realtime destinations share `type: 'destination'`; the only signal is the id prefix.
export function getHogFunctionDeliveryType(item: { id: string }): HogFunctionDeliveryType {
    return item.id.startsWith('batch-export-') ? 'batch' : 'realtime'
}

export function humanizeHogFunctionType(type: HogFunctionTypeType, plural: boolean = false): string {
    if (type === 'source_webhook') {
        return 'source' + (plural ? 's' : '')
    }
    if (type === 'site_app') {
        return 'Web script' + (plural ? 's' : '')
    }
    return type.replaceAll('_', ' ') + (plural ? 's' : '')
}
