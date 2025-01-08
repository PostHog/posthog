import { Meta, Story } from '@storybook/react'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from 'lib/ui/Dropdown/Dropdown'

import { Button } from '../Button/Button'

const meta: Meta = {
    title: 'UI/Dropdown',
}
export default meta

export const DropdownOpen: Story = () => {
    return (
        <div className="flex flex-col gap-64 items-start ph-fill-danger">
            <DropdownMenu defaultOpen>
                <DropdownMenuTrigger asChild>
                    {/* eslint-disable-next-line posthog/warn-elements */}
                    <Button intent="primary">Open bottom</Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent side="bottom" align="start" className="min-w-40">
                    <DropdownMenuLabel>My Account</DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem>Profile</DropdownMenuItem>
                    <DropdownMenuItem>Billing</DropdownMenuItem>
                    <DropdownMenuItem>Team</DropdownMenuItem>
                    <DropdownMenuItem>Subscription</DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
            <DropdownMenu defaultOpen>
                <DropdownMenuTrigger asChild>
                    {/* eslint-disable-next-line posthog/warn-elements */}
                    <Button intent="outline">Open bottom</Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent side="bottom" align="start" className="min-w-40">
                    <DropdownMenuLabel>My Account</DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem>Profile</DropdownMenuItem>
                    <DropdownMenuItem>Billing</DropdownMenuItem>
                    <DropdownMenuItem>Team</DropdownMenuItem>
                    <DropdownMenuItem>Subscription</DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
            <DropdownMenu defaultOpen>
                <DropdownMenuTrigger asChild>
                    {/* eslint-disable-next-line posthog/warn-elements */}
                    <Button intent="muted">Open bottom</Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent side="bottom" align="start" className="min-w-40">
                    <DropdownMenuLabel>My Account</DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem>Profile</DropdownMenuItem>
                    <DropdownMenuItem>Billing</DropdownMenuItem>
                    <DropdownMenuItem>Team</DropdownMenuItem>
                    <DropdownMenuItem>Subscription</DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
            {/* <DropdownMenu defaultOpen>
                <DropdownMenuTrigger asChild>
                    <Button intent="primary">Open top</Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent side="top" align="start" className="min-w-40">
                    <DropdownMenuLabel>My Account</DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem>Profile</DropdownMenuItem>
                    <DropdownMenuItem>Billing</DropdownMenuItem>
                    <DropdownMenuItem>Team</DropdownMenuItem>
                    <DropdownMenuItem>Subscription</DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu> */}
        </div>
    )
}
