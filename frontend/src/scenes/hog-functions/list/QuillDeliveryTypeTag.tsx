import { IconClock, IconLive } from '@posthog/icons'
import { Badge } from '@posthog/quill'

import { getHogFunctionDeliveryType } from '../hog-function-utils'

export function QuillDeliveryTypeTag({ item }: { item: { id: string } }): JSX.Element {
    return getHogFunctionDeliveryType(item) === 'batch' ? (
        <Badge variant="completed">
            <IconClock />
            Batch
        </Badge>
    ) : (
        <Badge variant="info">
            <IconLive />
            Realtime
        </Badge>
    )
}
