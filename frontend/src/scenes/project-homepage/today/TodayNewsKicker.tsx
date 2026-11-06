import { IconStack, IconStackItem, Text } from '@posthog/quill'

import type { NewsStoryApi } from 'products/today/frontend/generated/api.schemas'

import { TodayChange } from './TodayChange'
import { productIcon } from './todayRowIcons'

export function TodayNewsKicker({ story }: { story: NewsStoryApi }): JSX.Element {
    const icon = productIcon(story.product)

    return (
        <span className="flex items-center gap-2">
            <IconStack className="TodayRow__icons">
                <IconStackItem color={icon.color}>{icon.glyph}</IconStackItem>
            </IconStack>
            <Text size="xs" variant="muted" render={<span />}>
                {story.product_label}
            </Text>
            <TodayChange change={story.change} tone={story.tone} />
        </span>
    )
}
