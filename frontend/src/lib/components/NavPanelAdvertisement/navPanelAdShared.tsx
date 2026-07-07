import { useActions } from 'kea'

import type { SvgAssetComponent } from '@posthog/brand'
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

export interface ProductPushDisplay {
    /** Hoggie illustration shown in the promo card's hero image */
    Hoggie: SvgAssetComponent
    /** Product brand color driving the hero's geometric background */
    accentColor: string
    /** Default promo copy, used when the campaign has no custom reason text */
    tagline: string
}

// Playful scattered shapes behind the hoggie, tinted white over the product's brand color
function GeometricPattern(): JSX.Element {
    return (
        <svg
            className="absolute inset-0 h-full w-full text-white"
            viewBox="0 0 232 96"
            preserveAspectRatio="xMidYMid slice"
            aria-hidden="true"
        >
            <circle cx="26" cy="22" r="11" fill="currentColor" opacity="0.25" />
            <circle cx="204" cy="66" r="17" fill="none" stroke="currentColor" strokeWidth="3" opacity="0.3" />
            <rect
                x="176"
                y="10"
                width="15"
                height="15"
                rx="2"
                transform="rotate(18 183 17)"
                fill="currentColor"
                opacity="0.2"
            />
            <polygon points="64,10 75,30 53,30" fill="currentColor" opacity="0.3" />
            <path
                d="M8 62 l7 -8 7 8 7 -8 7 8"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                opacity="0.35"
            />
            <circle cx="118" cy="14" r="4" fill="currentColor" opacity="0.35" />
            <path
                d="M148 78 h12 M154 72 v12"
                stroke="currentColor"
                strokeWidth="3"
                strokeLinecap="round"
                opacity="0.3"
            />
            <circle cx="52" cy="78" r="6" fill="none" stroke="currentColor" strokeWidth="2.5" opacity="0.25" />
            <rect
                x="96"
                y="70"
                width="10"
                height="10"
                transform="rotate(-12 101 75)"
                fill="currentColor"
                opacity="0.18"
            />
            <polygon
                points="206,18 214,32 198,32"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinejoin="round"
                opacity="0.3"
            />
        </svg>
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
    text: string
    hero?: ProductPushDisplay
    onClose?: () => void
}): JSX.Element {
    const { hideAdvertisement } = useActions(navPanelAdvertisementLogic)

    const dismissButton = (
        <LemonButton
            icon={<IconX className={hero ? 'text-white' : 'text-muted'} />}
            tooltip="Dismiss"
            tooltipPlacement="right"
            size="xxsmall"
            className={hero ? 'bg-black/20 hover:bg-black/30' : undefined}
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
                <>
                    <div
                        className="relative flex h-24 items-center justify-center"
                        style={{ backgroundColor: hero.accentColor }}
                    >
                        <GeometricPattern />
                        <hero.Hoggie className="relative h-20 w-auto" aria-hidden="true" />
                        <div className="absolute inset-x-0 bottom-0 h-10 bg-gradient-to-b from-transparent to-surface-primary" />
                        <div className="absolute top-1 right-1">{dismissButton}</div>
                    </div>
                    <div className="flex flex-col gap-1 px-2 pt-0.5 pb-2">
                        <strong className="text-sm leading-tight">{title}</strong>
                        <p className="mb-0 text-secondary">{text}</p>
                    </div>
                </>
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
