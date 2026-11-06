import type { NewsStoryApi } from 'products/today/frontend/generated/api.schemas'

import { TodayChange } from './TodayChange'
import { productIcon } from './todayRowIcons'

export function TodayNewsKicker({
    story,
    showChange = true,
}: {
    story: NewsStoryApi
    showChange?: boolean
}): JSX.Element {
    return (
        <span className="flex items-center gap-1.5 font-mono text-xs tracking-wide text-muted-foreground uppercase [&_svg]:size-3.5">
            {productIcon(story.product).glyph}
            <span>{story.product_label}</span>
            {showChange ? <TodayChange change={story.change} tone={story.tone} /> : null}
        </span>
    )
}
