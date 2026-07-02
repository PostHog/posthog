import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'

import { AdvertisementCard, ProductPushDisplay } from './navPanelAdShared'
import { navPanelAdvertisementLogic } from './NavPanelAdvertisementLogic'
import { DEFAULT_PRODUCT_PUSH_DISPLAY, PRODUCT_PUSH_DISPLAY } from './NavPanelProductPushAd'

const meta = {
    title: 'Components/NavPanelProductPush',
    parameters: { layout: 'padded' },
} satisfies Meta<typeof AdvertisementCard>

export default meta
type Story = StoryObj<typeof meta>

/**
 * A card for a product push campaign. The campaign is the product key, the title is the product name, and the display is the product display.
 */
const PushCard = ({
    campaign,
    title,
    display,
}: {
    campaign: string
    title: string
    display: ProductPushDisplay
}): JSX.Element => (
    // The push card renders inside the (narrow) sidebar, so mirror that width here.
    <div className="w-[232px]">
        <div className="mb-1 font-mono text-xs text-muted">{campaign}</div>
        <BindLogic logic={navPanelAdvertisementLogic} props={{ campaign: `story-${campaign}` }}>
            <AdvertisementCard title={title} text={display.tagline} hero={display} />
        </BindLogic>
    </div>
)

// One card per pushable product, so a reviewer can eyeball every hoggie / brand color / tagline at once.
export const AllProducts: Story = {
    render: (): JSX.Element => {
        // 'session_replay' -> 'Session replay'. The live component titles the card with the product's
        // catalog label; a story has no catalog to resolve against, so humanize the key instead.
        const humanizeProductKey = (productKey: string): string => {
            const spaced = productKey.replace(/_/g, ' ')
            const sentence = spaced.charAt(0).toUpperCase() + spaced.slice(1)
            return sentence.replace(/^Llm\b/, 'LLM')
        }

        return (
            <div className="flex flex-wrap items-start gap-4">
                {(Object.entries(PRODUCT_PUSH_DISPLAY) as [string, ProductPushDisplay][]).map(
                    ([productKey, display]) => (
                        <PushCard
                            key={productKey}
                            campaign={productKey}
                            title={humanizeProductKey(productKey)}
                            display={display}
                        />
                    )
                )}
            </div>
        )
    },
}

// What a product key with no bespoke entry falls back to (e.g. a TAM-scheduled push of an unlisted product).
export const DefaultFallback: Story = {
    render: (): JSX.Element => (
        <PushCard campaign="default_fallback" title="Any other product" display={DEFAULT_PRODUCT_PUSH_DISPLAY} />
    ),
}
