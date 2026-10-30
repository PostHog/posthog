import { IconGlobe, IconRewindPlay, IconTrends } from '@posthog/icons'
import { Avatar, AvatarFallback } from '@posthog/quill'

import { Logomark } from 'lib/brand'

import type { TodayFeedAuthor } from './todayFeedItems'

const PRODUCT_AVATARS: Record<string, { color: string; glyph: JSX.Element }> = {
    product_analytics: { color: 'var(--color-product-product-analytics-light)', glyph: <IconTrends /> },
    web_analytics: { color: 'var(--color-product-web-analytics-light)', glyph: <IconGlobe /> },
    session_replay: { color: 'var(--color-product-session-replay-light)', glyph: <IconRewindPlay /> },
}

function initials(name: string): string {
    return name
        .split(/\s+/)
        .slice(0, 2)
        .map((part) => part[0]?.toUpperCase() ?? '')
        .join('')
}

export function TodayFeedAvatar({ author }: { author: TodayFeedAuthor }): JSX.Element {
    const product = author.product ? PRODUCT_AVATARS[author.product] : undefined
    if (product) {
        return (
            <span
                className="flex size-10 shrink-0 items-center justify-center rounded-full text-background [&_svg]:size-5"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ background: product.color }}
                aria-hidden
            >
                {product.glyph}
            </span>
        )
    }
    if (author.handle === '@posthog') {
        return (
            <span
                className="flex size-10 shrink-0 items-center justify-center rounded-full border border-border bg-card"
                aria-hidden
            >
                <Logomark className="w-6" />
            </span>
        )
    }
    return (
        <Avatar size="lg" className="size-10 shrink-0" aria-hidden>
            <AvatarFallback className="font-semibold">{initials(author.name)}</AvatarFallback>
        </Avatar>
    )
}
