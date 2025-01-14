import { IconAIText } from '@posthog/icons'
import { Meta, Story } from '@storybook/react'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from 'lib/ui/Dropdown/Dropdown'
import DropdownGen from 'lib/ui/Dropdown/DropdownGen'

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

export const DropdownGenExample: Story = () => {
    return (
        <DropdownGen
            id="dropdown-gen-example"
            loop
            align="start"
            side="bottom"
            button={
                <Button hasIcon iconLeft={<IconAIText />}>
                    Open Menu
                </Button>
            }
            items={[
                {
                    label: 'Item 1',
                    type: 'dropdown',
                    buttonProps: {
                        hasIcon: true,
                        iconLeft: <IconAIText />,
                    },
                    dropdownItems: [
                        {
                            label: 'Link to',
                            buttonProps: {
                                to: '/',
                                hasIcon: true,
                                iconLeft: <IconAIText />,
                            },
                        },
                        {
                            label: 'On click',
                            onClick: () => alert('Item 1.2'),
                            buttonProps: {
                                hasIcon: true,
                                iconLeft: <IconAIText />,
                            },
                        },
                        {
                            label: 'On click with exotic value',
                            value: { test: 'test' },
                            onClick: (value) => alert(`Item 1.3, value: ${value.test}`),
                            buttonProps: {
                                hasIcon: true,
                                iconLeft: <IconAIText />,
                            },
                        },
                    ],
                },
                {
                    label: 'Item 2',
                    type: 'combobox',
                    placeholder: 'Search for a fruit',
                    dropdownItems: [
                        { label: 'you say', value: 'potatoes' },
                        { label: 'I say', value: 'tomatoes', onClick: (value) => alert(value) },
                    ],
                },
            ]}
        />
    )
}
