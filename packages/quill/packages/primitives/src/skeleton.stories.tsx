import type { Meta, StoryObj } from '@storybook/react-vite'
import { useState } from 'react'

import { Button } from './button'
import { Card, CardTitle, CardHeader } from './card'
import { Skeleton } from './skeleton'

const meta = {
    title: 'Primitives/Skeleton',
    component: Skeleton,
    tags: ['autodocs'],
} satisfies Meta<typeof Skeleton>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => {
        const [isLoading, setIsLoading] = useState(true)

        return (
            <div className="flex flex-col gap-2 ">
                <div className="w-full max-w-sm">
                    Wrap the content in a Skeleton component to animate the opacity of the children when the loading
                    state changes. The container shouldn't change in size when the loading state changes.
                </div>
                <Button className="self-start" variant="outline" onClick={() => setIsLoading(!isLoading)}>
                    {isLoading ? 'Stop Loading' : 'Start Loading'}
                </Button>{' '}
                {isLoading ? (
                    <Skeleton className="w-full max-w-sm">
                        <Card>
                            <CardHeader>
                                <CardTitle>Not visible</CardTitle>
                            </CardHeader>
                        </Card>
                    </Skeleton>
                ) : (
                    <Card className="w-full max-w-sm">
                        <CardHeader>
                            <CardTitle>Hello</CardTitle>
                        </CardHeader>
                    </Card>
                )}
            </div>
        )
    },
} satisfies Story
