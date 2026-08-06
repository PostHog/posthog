import { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { Fade } from 'lib/components/Fade/Fade'

import { PRODUCT_CAPABILITIES } from '../maxCapabilities'
import {
    CAPABILITY_CARDS_HEIGHT_PX,
    CapabilityBadges as CapabilityBadgesComponent,
    CapabilitySuggestions,
} from './CapabilityBadges'

const meta: Meta = {
    title: 'Scenes-App/Max/Capability badges',
    parameters: { layout: 'centered' },
}
export default meta

type Story = StoryObj

// Mirrors the homepage swap area (see HomepageInput): a fixed-height box whose keyed `animate-fade-in`
// wrapper remounts on each selection change, so switching capabilities visibly fades the new cards in.
function BadgesWithSwap(): JSX.Element {
    const [selected, setSelected] = useState<string | null>(null)
    const capability = PRODUCT_CAPABILITIES.find((c) => c.key === selected) ?? null

    return (
        <div className="flex flex-col items-center gap-6 @container/main-content" style={{ width: 640 }}>
            <CapabilityBadgesComponent
                capabilities={PRODUCT_CAPABILITIES}
                selectedKey={selected}
                onSelect={setSelected}
            />
            <div className="w-full overflow-hidden" style={{ height: CAPABILITY_CARDS_HEIGHT_PX }}>
                <Fade visible key={selected ?? '__empty__'} className="h-full">
                    {capability ? (
                        <CapabilitySuggestions
                            capability={capability}
                            onType={() => {}}
                            onSubmit={() => {}}
                            onFillIn={() => {}}
                        />
                    ) : (
                        <div className="h-full flex items-center justify-center text-tertiary text-sm border border-dashed rounded">
                            Pick a capability above
                        </div>
                    )}
                </Fade>
            </div>
        </div>
    )
}

export const Interactive: Story = {
    render: () => <BadgesWithSwap />,
}
