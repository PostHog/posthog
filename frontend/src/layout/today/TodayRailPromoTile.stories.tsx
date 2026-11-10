import type { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import { BindLogic } from 'kea'

import { AdvertisementCard, NAV_PANEL_CARD_TYPE } from 'lib/components/NavPanelAdvertisement/navPanelAdShared'
import { navPanelAdvertisementLogic } from 'lib/components/NavPanelAdvertisement/NavPanelAdvertisementLogic'
import { PRODUCT_PUSH_DISPLAY } from 'lib/components/NavPanelAdvertisement/navPanelProductPushDisplay'

import { ProductKey } from '~/queries/schema/schema-general'

import { userEvent } from 'storybook/test'

import { TodayRailPromoTile } from './TodayRailPromoTile'
import { TODAY_RAIL_WIDTH } from './todayShellLogic'

const meta = {
    title: 'Layout/Today/Rail promo',
    parameters: { layout: 'padded' },
} satisfies Meta

export default meta
type Story = StoryObj<typeof meta>

const display = PRODUCT_PUSH_DISPLAY[ProductKey.SESSION_REPLAY]

// Opening the popover persists the card id as seen, so each story keys its own card to keep the unseen dot
// from depending on which story ran first.
function RailWithPromo({ cardId, withHoggie }: { cardId: string; withHoggie: boolean }): JSX.Element {
    return (
        // Sized so the opened card fits beside the rail, because the snapshot grows to include the popover.
        <div data-quill className="Today flex h-[420px] w-[340px] bg-[var(--chrome)]">
            <nav
                aria-label="Main"
                className="flex shrink-0 flex-col items-center gap-3 pt-3 pb-3"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ width: TODAY_RAIL_WIDTH }}
            >
                <div className="mt-auto flex w-full flex-col items-center gap-3">
                    <TodayRailPromoTile
                        card={
                            <BindLogic logic={navPanelAdvertisementLogic} props={{ dismissKey: cardId }}>
                                <AdvertisementCard
                                    title="Session replay"
                                    text={display?.tagline ?? ''}
                                    hero={display}
                                />
                            </BindLogic>
                        }
                        teaser={{
                            id: cardId,
                            cardType: NAV_PANEL_CARD_TYPE.PRODUCT_PUSH,
                            title: 'Session replay',
                            Hoggie: withHoggie ? display?.Hoggie : undefined,
                        }}
                    />
                </div>
            </nav>
        </div>
    )
}

export const Unopened: Story = {
    render: () => <RailWithPromo cardId="story-rail-promo-unopened" withHoggie />,
}

export const Opened: Story = {
    render: () => <RailWithPromo cardId="story-rail-promo-opened" withHoggie />,
    parameters: { testOptions: { waitForSelector: '[data-slot="popover-content"]' } },
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByRole('button', { name: /For you/ }))
    },
}

export const WithoutAHoggie: Story = {
    render: () => <RailWithPromo cardId="story-rail-promo-without-a-hoggie" withHoggie={false} />,
}
