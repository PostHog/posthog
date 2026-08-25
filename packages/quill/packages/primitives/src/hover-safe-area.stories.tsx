import { PreviewCard } from '@base-ui/react/preview-card'
import type { Meta, StoryObj } from '@storybook/react'
import { useRef } from 'react'

import { Button } from './button'
import { Card, CardContent, CardHeader, CardTitle } from './card'
import { HoverSafeArea } from './hover-safe-area'
import { Text } from './text'

const meta = {
    title: 'Primitives/HoverSafeArea',
    component: HoverSafeArea,
    tags: ['autodocs'],
} satisfies Meta<typeof HoverSafeArea>

export default meta
type Story = StoryObj<typeof meta>

export const PreviewCardCorridor: Story = {
    render: () => {
        const anchorRef = useRef<HTMLElement | null>(null)
        const positionerRef = useRef<HTMLDivElement | null>(null)

        return (
            <PreviewCard.Root>
                <div className="flex w-48 flex-col items-stretch gap-1">
                    <PreviewCard.Trigger ref={anchorRef} delay={0} closeDelay={0} render={<Button variant="outline" />}>
                        Hover for details
                    </PreviewCard.Trigger>
                    <Button variant="default">Nearby row</Button>
                    <Button variant="default">Another nearby row</Button>
                </div>
                <PreviewCard.Portal>
                    <HoverSafeArea anchorRef={anchorRef} floatingRef={positionerRef} />
                    <PreviewCard.Positioner ref={positionerRef} side="right" sideOffset={24} align="start">
                        <PreviewCard.Popup render={<Card className="w-64" />}>
                            <CardHeader>
                                <CardTitle>Preview details</CardTitle>
                            </CardHeader>
                            <CardContent>
                                <Text size="sm">Move diagonally from the trigger to this card.</Text>
                            </CardContent>
                        </PreviewCard.Popup>
                    </PreviewCard.Positioner>
                </PreviewCard.Portal>
            </PreviewCard.Root>
        )
    },
} satisfies Story
