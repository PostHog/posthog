import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { Button } from './button'
import { Card } from './card'
import { SkeletonText } from './skeleton-text'

const meta = {
    title: 'Primitives/SkeletonText',
    component: SkeletonText,
    tags: ['autodocs'],
} satisfies Meta<typeof SkeletonText>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => {
        const [isLoading, setIsLoading] = useState(false)

        return (
            <div className="flex flex-col gap-2 ">
                <div className="w-full max-w-sm">
                    The containers shouldn't change in size when the loading state changes.
                </div>
                <Button className="self-start" variant="outline" onClick={() => setIsLoading(!isLoading)}>
                    {isLoading ? 'Stop Loading' : 'Start Loading'}
                </Button>{' '}
                <hr />
                <Card className="max-w-sm border border-border rounded-md p-2 text-base">
                    {isLoading ? (
                        <SkeletonText lines={1} className="text-base" />
                    ) : (
                        <p className="text-base">Single line of text.</p>
                    )}
                </Card>
                <Card className="max-w-sm border border-border rounded-md p-2 text-base">
                    {isLoading ? (
                        <SkeletonText lines={2} className="text-base" />
                    ) : (
                        <p className="text-base">
                            Text base size. Pass in the tailwind text size class to the className prop to match the text
                            size.
                        </p>
                    )}
                </Card>
                <Card className="max-w-sm border border-border rounded-md p-2 text-base">
                    {isLoading ? (
                        <SkeletonText lines={3} className="text-xl" />
                    ) : (
                        <p className="text-xl">
                            Text xl size. Pass in the tailwind text size class to the className prop to match the text
                            size.
                        </p>
                    )}
                </Card>
            </div>
        )
    },
} satisfies Story
