import { useActions } from 'kea'
import { useRef } from 'react'

import type { AssetSvgProps } from '@posthog/brand'
import { IconX } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { navPanelAdvertisementLogic } from './NavPanelAdvertisementLogic'

/**
 * Which card filled the ad slot, sent as `card_type` on every ad-slot event.
 *
 * A broadcast is hand-authored in a feature flag and targeted by whoever wrote it. A product push
 * is chosen by the growth scheduler from an organization's `ProductPushCampaign` queue. Two cards
 * shared one event name once before, which made their impressions indistinguishable, so every
 * ad-slot event states its card outright.
 */
// pinned: analytics property values — renaming breaks dashboards
export const NAV_PANEL_CARD_TYPE = {
    BROADCAST: 'broadcast',
    PRODUCT_PUSH: 'product_push',
} as const

export interface BroadcastPayload {
    /** Slug identifying this broadcast, e.g. 'managed-warehouse-beta'. Keys dismissal state. */
    broadcast: string
    text: string
    emoji: string
    emojiLabel: string
    title: string
    /**
     * ProductKey the broadcast advertises, e.g. 'session_replay'. Optional, because a broadcast
     * need not be about a product at all (a legal notice, say). Set it whenever the broadcast does
     * promote one, so its impressions can be compared against the product push for that product.
     */
    productKey?: string
}

export function isBroadcastPayload(value: unknown): value is BroadcastPayload {
    return (
        typeof value === 'object' &&
        value !== null &&
        typeof (value as BroadcastPayload).broadcast === 'string' &&
        typeof (value as BroadcastPayload).text === 'string' &&
        typeof (value as BroadcastPayload).emoji === 'string' &&
        typeof (value as BroadcastPayload).emojiLabel === 'string' &&
        typeof (value as BroadcastPayload).title === 'string' &&
        ['undefined', 'string'].includes(typeof (value as BroadcastPayload).productKey)
    )
}

/** Where the hog sits along the card's bottom edge, so each illustration can be framed on its own terms. */
export interface HoggieOffset {
    /** Horizontal center of the hog, as a percentage of the card's width. 0 is the left edge, 100 the right. */
    x?: number
    /** Share of the hog's own height hidden below the card's bottom edge. */
    y?: number
}

export interface ProductPushDisplay {
    /** Hoggie illustration shown at the bottom of the promo card (a PNG, via `pngHoggie`). Mutually
     * exclusive with `Icon` — a card shows one or the other. */
    Hoggie?: React.ComponentType<AssetSvgProps>
    /** Pre-rendered brand logo shown instead of a Hoggie, for surfaces that aren't catalog products.
     * The card positions and rotates it; the element carries its own size and color. */
    Icon?: JSX.Element
    /** Render `Icon` upright instead of the default slight rotation (the PostHog logomark reads wrong tilted). */
    iconUpright?: boolean
    /** Product brand color, used for the title and - mixed down - its highlight */
    accentColor: string
    /** Default promo copy, used when the campaign has no custom reason text */
    tagline: string
    /** Overrides the default framing of `Hoggie`, for illustrations that sit off-balance in their own bounds */
    hoggieOffset?: HoggieOffset
    /** Card title for a growth surface, which has no product catalog entry to resolve a name from */
    label?: string
    /** Destination the card links to. Absolute URL for external surfaces, in-app path otherwise. */
    href?: string
}

const DEFAULT_HOGGIE_OFFSET: Required<HoggieOffset> = { x: 50, y: 22 }

/**
 * Presentational product "text + hog" promo: the product name highlighted in its brand color, a
 * blurb, and a Hoggie illustration running off the card's bottom edge. Shared by the nav
 * advertisement card and the welcome dialog's flagship-products showcase so both read as one
 * visual. The illustration is clipped by the caller's `overflow-hidden`. ``topRightGutter`` keeps
 * the title clear of a control the caller overlays on the card's top-right corner; the welcome
 * showcase has no such control.
 */
export function ProductHogHero({
    hero,
    title,
    text,
    topRightGutter,
}: {
    hero: ProductPushDisplay
    title: string
    text: React.ReactNode
    topRightGutter?: boolean
}): JSX.Element {
    const { x, y } = { ...DEFAULT_HOGGIE_OFFSET, ...hero.hoggieOffset }

    return (
        <div className="flex flex-col gap-1 px-2 pt-2">
            <div className={`flex items-start ${topRightGutter ? 'pr-7' : ''}`}>
                <strong
                    className="rounded-sm px-1 py-px text-sm leading-tight"
                    style={{
                        // Pulled towards the theme's text color so pale brand accents stay legible on
                        // light backgrounds and dark ones on the dark theme, without losing their hue.
                        color: `color-mix(in srgb, ${hero.accentColor} 78%, var(--color-text-primary))`,
                        backgroundColor: `color-mix(in srgb, ${hero.accentColor} 18%, transparent)`,
                    }}
                >
                    {title}
                </strong>
            </div>
            <p className="mb-0 text-secondary">{text}</p>
            {hero.Icon ? (
                // A surface has no hoggie: show its own logo toward the bottom-right, tilted by
                // default (uprighted for marks that read wrong at an angle, e.g. the PostHog logo).
                <div className="relative -mx-2 -mt-1 h-24 overflow-hidden" aria-hidden="true">
                    <div className={`absolute bottom-3 right-4 ${hero.iconUpright ? '' : 'rotate-[14deg]'}`}>
                        {hero.Icon}
                    </div>
                </div>
            ) : hero.Hoggie ? (
                // Pulled out of the card's horizontal padding so `x` is a share of the full card width
                <div className="relative -mx-2 -mt-1 h-32">
                    {/* Oversized rather than nudged down, so the part `y` hides below the edge does not
                        open an equal gap above the hog. */}
                    <hero.Hoggie
                        className="absolute top-0 w-auto max-w-none"
                        style={{ left: `${x}%`, height: `${100 / (1 - y / 100)}%`, transform: 'translateX(-50%)' }}
                        aria-hidden="true"
                    />
                </div>
            ) : null}
        </div>
    )
}

/**
 * How long after the card appears a click on its dismiss control is ignored.
 *
 * The card loads after the nav is already interactive, so it can slide into the footer under a
 * cursor that was aimed at a nav link. A click that lands in the first moments is a mis-aim, not a
 * decision to dismiss.
 */
export const DISMISS_SETTLE_MS = 500

export function AdvertisementCard({
    emoji,
    emojiLabel,
    title,
    text,
    hero,
    onClose,
    to,
    target,
    onLinkClick,
}: {
    emoji?: string
    emojiLabel?: string
    title: string
    text: React.ReactNode
    hero?: ProductPushDisplay
    onClose?: () => void
    /** Destination the card body links to. The dismiss control stays outside this link. */
    to?: string
    target?: string
    onLinkClick?: () => void
}): JSX.Element {
    const { hideAdvertisement } = useActions(navPanelAdvertisementLogic)
    const appearedAt = useRef(Date.now())

    const body = hero ? (
        <ProductHogHero hero={hero} title={title} text={text} topRightGutter />
    ) : (
        <div className="flex flex-col gap-1 px-2 py-1.5">
            <strong className="pr-7">
                {emoji ? (
                    <>
                        <span role="img" aria-label={emojiLabel}>
                            {emoji}
                        </span>{' '}
                    </>
                ) : null}
                {title}
            </strong>
            <p className="mb-0 text-secondary">{text}</p>
        </div>
    )

    return (
        // The gap to the nav footer's buttons belongs to the card, not the footer, so it goes away
        // with the card when there is nothing to advertise.
        <div className="relative mb-2 overflow-hidden rounded border bg-surface-primary text-xs shadow-sm transition-shadow hover:shadow-md">
            {to ? (
                <Link to={to} target={target} className="block text-primary" onClick={onLinkClick}>
                    {body}
                </Link>
            ) : (
                body
            )}
            {/* Overlaid rather than placed next to the title, so the control sits outside the
                card's link and only dismisses where the button is actually drawn. */}
            <div className="absolute right-1 top-1">
                <LemonButton
                    icon={<IconX className="text-muted" />}
                    tooltip="Dismiss"
                    tooltipPlacement="right"
                    size="small"
                    onClick={() => {
                        if (Date.now() - appearedAt.current < DISMISS_SETTLE_MS) {
                            return
                        }

                        onClose?.()

                        hideAdvertisement()
                    }}
                />
            </div>
        </div>
    )
}
