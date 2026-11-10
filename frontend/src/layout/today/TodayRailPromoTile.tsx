import { useActions, useValues } from 'kea'

import * as megaphonePng from '@posthog/brand/hoggies/png/megaphone'
import { Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { pngHoggie } from 'lib/brand/hoggies'
import type { NavPanelCardTeaser } from 'lib/components/NavPanelAdvertisement/navPanelAdShared'

import { todayRailPromoLogic } from './todayRailPromoLogic'
import { TodayRailTile } from './TodayRailTile'

// A broadcast, or a push for a surface that shows a logo instead of a hog, has no hoggie of its own.
const DefaultHoggie = pngHoggie(megaphonePng)

export function TodayRailPromoTile({ card, teaser }: { card: JSX.Element; teaser: NavPanelCardTeaser }): JSX.Element {
    const { promoOpen, openedTeaserIds } = useValues(todayRailPromoLogic)
    const { openPromo, closePromo } = useActions(todayRailPromoLogic)
    const Hoggie = teaser.Hoggie ?? DefaultHoggie
    const unseen = !openedTeaserIds.includes(teaser.id)

    return (
        <Popover open={promoOpen} onOpenChange={(open) => (open ? openPromo(teaser) : closePromo())}>
            <PopoverTrigger
                render={
                    <TodayRailTile
                        label="For you"
                        icon={<Hoggie className="size-8 object-contain" />}
                        active={promoOpen}
                        dataAttr="today-rail-promo"
                        severity={unseen ? 'notice' : 'none'}
                        aria-label={`For you: ${teaser.title}`}
                    />
                }
            />
            {/* The card draws its own surface, so the popover adds only the positioning. */}
            <PopoverContent
                side="right"
                align="end"
                sideOffset={8}
                // The card's first tabbable control is its dismiss button. Focusing it on a pointer open pops
                // its tooltip over the card, so only a keyboard open moves focus into the card.
                initialFocus={(openType) => openType === 'keyboard'}
                className="w-60 gap-0 border-0 bg-transparent p-0 shadow-none"
            >
                {card}
            </PopoverContent>
        </Popover>
    )
}
