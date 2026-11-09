import { IconStack, IconStackItem, Text } from '@posthog/quill'

import { TodayChange } from './TodayChange'
import { productIcon } from './todayRowIcons'
import type { TodayTone } from './todayTone'

export function TodayNewsKicker({
    product,
    productLabel,
    change = null,
    tone,
}: {
    product: string
    productLabel: string
    change?: number | null
    tone: TodayTone
}): JSX.Element {
    const icon = productIcon(product)

    return (
        <span className="flex items-center gap-2">
            <IconStack className="TodayRow__icons">
                <IconStackItem color={icon.color}>{icon.glyph}</IconStackItem>
            </IconStack>
            <Text size="xs" variant="muted" render={<span />}>
                {productLabel}
            </Text>
            <TodayChange change={change} tone={tone} />
        </span>
    )
}
