import { TodayChange } from './TodayChange'
import type { TodayNewsStory } from './todayNewsEdition'
import { productIcon } from './todayRowIcons'

export function TodayNewsKicker({
    story,
    showChange = true,
}: {
    story: TodayNewsStory
    showChange?: boolean
}): JSX.Element {
    return (
        <span className="flex items-center gap-1.5 font-mono text-xs tracking-wide text-muted-foreground uppercase [&_svg]:size-3.5">
            {productIcon(story.product).glyph}
            <span>{story.productLabel}</span>
            {showChange ? <TodayChange change={story.change} tone={story.tone} /> : null}
        </span>
    )
}
