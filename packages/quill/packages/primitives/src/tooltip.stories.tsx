import type { Meta, StoryObj } from '@storybook/react'
import { InfoIcon } from 'lucide-react'
import { useState } from 'react'

import { Button } from './button'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from './tooltip'

const meta = {
    title: 'Primitives/Tooltips',
    component: Tooltip,
    tags: ['autodocs'],
} satisfies Meta<typeof Tooltip>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => {
        return (
            <TooltipProvider>
                <div className="max-w-sm flex gap-2 min-h-96 items-center justify-center border">
                    <div className="flex flex-col gap-2 items-center">
                        <Tooltip>
                            <TooltipTrigger
                                render={
                                    <Button className="self-start" variant="outline">
                                        Hover me
                                    </Button>
                                }
                            />
                            <TooltipContent>The tooltip is hoverable and focusable.</TooltipContent>
                        </Tooltip>
                    </div>
                </div>
            </TooltipProvider>
        )
    },
} satisfies Story

export const Controlled: Story = {
    render: () => {
        const [isVisible, setIsVisible] = useState(true)

        return (
            <TooltipProvider>
                <div className="max-w-sm flex gap-2 min-h-96 items-center justify-center border">
                    <div className="flex flex-col gap-2 items-center">
                        <Tooltip open={isVisible} onOpenChange={setIsVisible}>
                            <TooltipTrigger
                                render={
                                    <Button className="self-start" variant="outline">
                                        Default open
                                    </Button>
                                }
                            />
                            <TooltipContent>The tooltip is open by default.</TooltipContent>
                        </Tooltip>
                    </div>
                </div>
            </TooltipProvider>
        )
    },
} satisfies Story

export const Directions: Story = {
    render: () => {
        const [isVisible, setIsVisible] = useState(true)

        return (
            <TooltipProvider>
                <div className="relative grid grid-cols-3 grid-rows-3 w-80 h-80 border rounded-md p-12">
                    <div className="col-start-2 row-start-1 flex items-start justify-center pt-2">
                        <Tooltip open={isVisible} onOpenChange={setIsVisible}>
                            <TooltipTrigger render={<Button variant="outline">Default</Button>} />
                            <TooltipContent side="top">
                                <button>top</button>
                            </TooltipContent>
                        </Tooltip>
                    </div>
                    <div className="col-start-3 row-start-2 flex items-center justify-end pr-2">
                        <Tooltip open={isVisible} onOpenChange={setIsVisible}>
                            <TooltipTrigger render={<Button variant="outline">Right</Button>} />
                            <TooltipContent side="right">
                                <button>right</button>
                            </TooltipContent>
                        </Tooltip>
                    </div>
                    <div className="col-start-2 row-start-3 flex items-end justify-center pb-2">
                        <Tooltip open={isVisible} onOpenChange={setIsVisible}>
                            <TooltipTrigger render={<Button variant="outline">Bottom</Button>} />
                            <TooltipContent side="bottom">
                                <button>bottom</button>
                            </TooltipContent>
                        </Tooltip>
                    </div>
                    <div className="col-start-1 row-start-2 flex items-center justify-start pl-2">
                        <Tooltip open={isVisible} onOpenChange={setIsVisible}>
                            <TooltipTrigger render={<Button variant="outline">Left</Button>} />
                            <TooltipContent side="left">
                                <button>left</button>
                            </TooltipContent>
                        </Tooltip>
                    </div>
                </div>
            </TooltipProvider>
        )
    },
} satisfies Story

export const IconOnlyTriggers: Story = {
    render: () => {
        return (
            <TooltipProvider>
                <div className="max-w-sm flex gap-2 min-h-96 items-center justify-center border">
                    <div className="flex flex-col gap-2 items-center gap-8">
                        <Tooltip>
                            <div className="flex flex-col gap-2 items-center">
                                Delay 0
                                <TooltipTrigger
                                    delay={0}
                                    render={
                                        <Button size="icon" variant="outline">
                                            <InfoIcon className="size-4" />
                                        </Button>
                                    }
                                />
                            </div>
                            <TooltipContent>Icon only tooltip trigger should open immediately.</TooltipContent>
                        </Tooltip>
                    </div>
                </div>
            </TooltipProvider>
        )
    },
} satisfies Story
