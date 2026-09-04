import { useActions } from 'kea'

import type { AssetSvgProps } from '@posthog/brand'
import { IconX } from '@posthog/icons'

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
    /** Soft purple glow behind `Icon`, echoing the AI surfaces' sidebar treatment. */
    iconBackdrop?: boolean
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
 * visual. The illustration is clipped by the caller's `overflow-hidden`. ``topRight`` is an
 * optional slot for a control next to the title (e.g. a dismiss button); the welcome showcase
 * leaves it empty.
 */
export function ProductHogHero({
    hero,
    title,
    text,
    topRight,
}: {
    hero: ProductPushDisplay
    title: string
    text: React.ReactNode
    topRight?: JSX.Element
}): JSX.Element {
    const { x, y } = { ...DEFAULT_HOGGIE_OFFSET, ...hero.hoggieOffset }

    return (
        <div className="flex flex-col gap-1 px-2 pt-2">
            <div className="flex items-start justify-between gap-1">
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
                {topRight}
            </div>
            <p className="mb-0 text-secondary">{text}</p>
            {hero.Icon ? (
                // A surface has no hoggie: show its own logo toward the bottom-right, tilted by
                // default (uprighted for marks that read wrong at an angle, e.g. the PostHog logo).
                <div className="relative -mx-2 -mt-1 h-24 overflow-hidden" aria-hidden="true">
                    <div className={`absolute bottom-3 right-4 ${hero.iconUpright ? '' : 'rotate-[14deg]'}`}>
                        {hero.iconBackdrop ? (
                            <div className="absolute inset-0 scale-75 rounded-full bg-[var(--color-purple-200)] opacity-70 blur-lg" />
                        ) : null}
                        <div className="relative">{hero.Icon}</div>
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

export function AdvertisementCard({
    emoji,
    emojiLabel,
    title,
    text,
    hero,
    onClose,
}: {
    emoji?: string
    emojiLabel?: string
    title: string
    text: React.ReactNode
    hero?: ProductPushDisplay
    onClose?: () => void
}): JSX.Element {
    const { hideAdvertisement } = useActions(navPanelAdvertisementLogic)

    const dismissButton = (
        <LemonButton
            icon={<IconX className="text-muted" />}
            tooltip="Dismiss"
            tooltipPlacement="right"
            size="xxsmall"
            onClick={(e) => {
                e.preventDefault()
                e.stopPropagation()

                onClose?.()

                hideAdvertisement()
            }}
            noPadding
        />
    )

    return (
        <div className="overflow-hidden rounded border bg-surface-primary text-xs shadow-sm transition-shadow hover:shadow-md">
            {hero ? (
                <ProductHogHero hero={hero} title={title} text={text} topRight={dismissButton} />
            ) : (
                <div className="flex flex-col gap-1 px-2 py-1.5">
                    <div className="flex items-start justify-between gap-2">
                        <strong>
                            {emoji ? (
                                <>
                                    <span role="img" aria-label={emojiLabel}>
                                        {emoji}
                                    </span>{' '}
                                </>
                            ) : null}
                            {title}
                        </strong>
                        {dismissButton}
                    </div>
                    <p className="mb-0 text-secondary">{text}</p>
                </div>
            )}
        </div>
    )
}
