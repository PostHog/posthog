import { useActions } from 'kea'

import type { AssetSvgProps } from '@posthog/brand'
import { IconX } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { navPanelAdvertisementLogic } from './NavPanelAdvertisementLogic'

export interface CampaignPayload {
    campaign: string
    text: string
    emoji: string
    emojiLabel: string
    title: string
}

export function isCampaignPayload(value: unknown): value is CampaignPayload {
    return (
        typeof value === 'object' &&
        value !== null &&
        typeof (value as CampaignPayload).campaign === 'string' &&
        typeof (value as CampaignPayload).text === 'string' &&
        typeof (value as CampaignPayload).emoji === 'string' &&
        typeof (value as CampaignPayload).emojiLabel === 'string' &&
        typeof (value as CampaignPayload).title === 'string'
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
    /** Hoggie illustration shown at the bottom of the promo card (a PNG, via `pngHoggie`) */
    Hoggie: React.ComponentType<AssetSvgProps>
    /** Product brand color, used for the title and - mixed down - its highlight */
    accentColor: string
    /** Default promo copy, used when the campaign has no custom reason text */
    tagline: string
    /** Overrides the default framing of `Hoggie`, for illustrations that sit off-balance in their own bounds */
    hoggieOffset?: HoggieOffset
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
            {/* Pulled out of the card's horizontal padding so `x` is a share of the full card width */}
            <div className="relative -mx-2 -mt-1 h-32">
                {/* Oversized rather than nudged down, so the part `y` hides below the edge does not
                    open an equal gap above the hog. */}
                <hero.Hoggie
                    className="absolute top-0 w-auto max-w-none"
                    style={{ left: `${x}%`, height: `${100 / (1 - y / 100)}%`, transform: 'translateX(-50%)' }}
                    aria-hidden="true"
                />
            </div>
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
