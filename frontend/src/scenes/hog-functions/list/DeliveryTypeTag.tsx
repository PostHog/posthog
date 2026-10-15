import { IconClock, IconLive } from '@posthog/icons'
import { LemonSelectOptions, LemonTag } from '@posthog/lemon-ui'

import { HogFunctionDeliveryType, getHogFunctionDeliveryType } from '../hog-function-utils'

// Batch exports vs realtime destinations (hog functions) in the new-destination picker, which
// is the one list that still mixes both kinds of templates.
export function DeliveryTypeTag({ item }: { item: { id: string } }): JSX.Element {
    return getHogFunctionDeliveryType(item) === 'batch' ? (
        <LemonTag type="completion" icon={<IconClock />} className="text-xs">
            Batch
        </LemonTag>
    ) : (
        <LemonTag type="highlight" icon={<IconLive />} className="text-xs">
            Realtime
        </LemonTag>
    )
}

export const DELIVERY_TYPE_FILTER_OPTIONS: LemonSelectOptions<HogFunctionDeliveryType | null> = [
    { label: 'All types', value: null },
    { label: 'Realtime', value: 'realtime' },
    { label: 'Batch', value: 'batch' },
]
