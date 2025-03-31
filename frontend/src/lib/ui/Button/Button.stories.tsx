import { IconSearch } from '@posthog/icons'
import type { Meta } from '@storybook/react'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'

// import { Button } from './Button'
import { Button } from './Button'

const meta = {
    title: 'UI/Button',
    component: Button.Root,
    tags: ['autodocs'],
} satisfies Meta<typeof Button.Root>

export default meta

export function Default(): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <Button.Root intent="outline">
                <Button.Label>Regular button</Button.Label>
            </Button.Root>

            <Button.Root intent="outline" className="max-w-[105px]">
                <Button.Label truncate>Truncated</Button.Label>
                <Button.Icon>
                    <IconSearch />
                </Button.Icon>
            </Button.Root>

            <Button.Root disabled intent="outline">
                <Button.Label>disabled</Button.Label>
            </Button.Root>

            <Button.Root intent="outline">
                <Button.Icon>
                    <IconSearch />
                </Button.Icon>
            </Button.Root>

            <Button.Root intent="outline">
                <Button.Label>with icon</Button.Label>
                <Button.Icon>
                    <IconSearch />
                </Button.Icon>
            </Button.Root>

            <Button.Root intent="outline" fullWidth>
                <Button.Label>full width</Button.Label>
                <Button.Icon>
                    <IconSearch />
                </Button.Icon>
            </Button.Root>

            <Button.Root intent="outline" menuItem>
                <Button.Icon>
                    <IconSearch />
                </Button.Icon>
                <Button.Label menuItem as="mark">
                    menu item with icons
                </Button.Label>
                <Button.Icon>
                    <IconSearch />
                </Button.Icon>
            </Button.Root>

            <Button.Root intent="outline" menuItem>
                <Button.Icon isTrigger isTriggerLeft>
                    <IconSearch />
                </Button.Icon>
                <Button.Label menuItem>menu item with trigger (side action)</Button.Label>
            </Button.Root>

            <Button.Root intent="outline" menuItem>
                <Button.Label menuItem>menu item with trigger (side action)</Button.Label>
                <Button.Icon isTrigger isTriggerRight>
                    <IconSearch />
                </Button.Icon>
            </Button.Root>

            <Button.Root intent="outline" menuItem>
                <Button.Icon isTrigger isTriggerLeft>
                    <IconSearch />
                </Button.Icon>
                <Button.Label menuItem>menu item with trigger (side action)</Button.Label>
                <Button.Icon isTrigger isTriggerRight>
                    <IconSearch />
                </Button.Icon>
            </Button.Root>

            <DropdownMenu>
                <DropdownMenuTrigger asChild>
                    <Button.Root intent="outline">
                        <Button.Icon>
                            <IconSearch />
                        </Button.Icon>
                    </Button.Root>
                </DropdownMenuTrigger>

                {/* The Dropdown content menu */}
                <DropdownMenuContent loop align="start">
                    <DropdownMenuLabel>Projects</DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem asChild>
                        <Button.Root size="sm" menuItem>
                            <Button.Label>Project 1</Button.Label>
                        </Button.Root>
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                        <Button.Root size="sm" menuItem>
                            <Button.Label>Project 2</Button.Label>
                        </Button.Root>
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>

            <DropdownMenu>
                <DropdownMenuTrigger asChild>
                    <Button.Root>
                        <Button.Icon>
                            <IconSearch />
                        </Button.Icon>
                        <Button.Label>Is all dropdown</Button.Label>
                    </Button.Root>
                </DropdownMenuTrigger>

                {/* The Dropdown content menu */}
                <DropdownMenuContent loop align="start">
                    <DropdownMenuLabel>Section 1</DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem asChild>
                        <Button.Root menuItem>
                            <Button.Label>Item 2</Button.Label>
                        </Button.Root>
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                        <Button.Root menuItem>
                            <Button.Label>Item 3</Button.Label>
                        </Button.Root>
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>

            <Button.Root>
                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <Button.Icon as="button" isTrigger showTriggerDivider isTriggerLeft>
                            <IconSearch />
                        </Button.Icon>
                    </DropdownMenuTrigger>

                    <DropdownMenuContent loop align="start">
                        <DropdownMenuLabel>Projects</DropdownMenuLabel>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem asChild>
                            <Button.Root menuItem>
                                <Button.Label>Item 1</Button.Label>
                            </Button.Root>
                        </DropdownMenuItem>
                        <DropdownMenuItem asChild>
                            <Button.Root menuItem>
                                <Button.Label>Item 2</Button.Label>
                            </Button.Root>
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>

                <Button.Label>Has two side actions dropdown</Button.Label>

                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <Button.Icon as="button" isTrigger showTriggerDivider isTriggerRight>
                            <IconSearch />
                        </Button.Icon>
                    </DropdownMenuTrigger>

                    <DropdownMenuContent loop align="start">
                        <DropdownMenuLabel>Projects</DropdownMenuLabel>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem asChild>
                            <Button.Root size="sm" menuItem>
                                <Button.Label>Item 1</Button.Label>
                            </Button.Root>
                        </DropdownMenuItem>
                        <DropdownMenuItem asChild>
                            <Button.Root size="sm" menuItem>
                                <Button.Label>Item 2</Button.Label>
                            </Button.Root>
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            </Button.Root>
        </div>
    )
}

export function Sizes(): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <div className="flex gap-4">
                <Button.Root size="sm">
                    <Button.Label>Small button</Button.Label>
                </Button.Root>
                <Button.Root size="sm" intent="outline">
                    <Button.Label>Small button</Button.Label>
                </Button.Root>
                <Button.Root size="sm">
                    <Button.Icon>
                        <IconSearch />
                    </Button.Icon>
                    <Button.Label>Small button</Button.Label>
                </Button.Root>
                <Button.Root intent="outline" size="sm">
                    <Button.Icon isTrigger isTriggerLeft>
                        <IconSearch />
                    </Button.Icon>
                    <Button.Label>menu item with trigger (side action)</Button.Label>
                    <Button.Icon isTrigger isTriggerRight>
                        <IconSearch />
                    </Button.Icon>
                </Button.Root>
                <Button.Root size="sm">
                    <Button.Icon>
                        <IconSearch />
                    </Button.Icon>
                </Button.Root>
                <Button.Root size="sm" intent="outline">
                    <Button.Icon>
                        <IconSearch />
                    </Button.Icon>
                </Button.Root>
            </div>
            <div className="flex gap-4">
                <Button.Root size="base">
                    <Button.Label>Base button</Button.Label>
                </Button.Root>
                <Button.Root size="base" intent="outline">
                    <Button.Label>Base button</Button.Label>
                </Button.Root>
                <Button.Root size="base">
                    <Button.Icon>
                        <IconSearch />
                    </Button.Icon>
                    <Button.Label>Base button</Button.Label>
                </Button.Root>
                <Button.Root intent="outline" size="base">
                    <Button.Icon isTrigger isTriggerLeft>
                        <IconSearch />
                    </Button.Icon>
                    <Button.Label>menu item with trigger (side action)</Button.Label>
                    <Button.Icon isTrigger isTriggerRight>
                        <IconSearch />
                    </Button.Icon>
                </Button.Root>
                <Button.Root size="base">
                    <Button.Icon>
                        <IconSearch />
                    </Button.Icon>
                </Button.Root>
                <Button.Root size="base" intent="outline">
                    <Button.Icon>
                        <IconSearch />
                    </Button.Icon>
                </Button.Root>
            </div>

            <div className="flex gap-4">
                <Button.Root size="lg">
                    <Button.Label>Large button</Button.Label>
                </Button.Root>
                <Button.Root size="lg" intent="outline">
                    <Button.Label>Large button</Button.Label>
                </Button.Root>
                <Button.Root size="lg">
                    <Button.Icon>
                        <IconSearch />
                    </Button.Icon>
                    <Button.Label>Large button</Button.Label>
                </Button.Root>
                <Button.Root intent="outline" size="lg">
                    <Button.Icon isTrigger isTriggerLeft>
                        <IconSearch />
                    </Button.Icon>
                    <Button.Label>menu item with trigger (side action)</Button.Label>
                    <Button.Icon isTrigger isTriggerRight>
                        <IconSearch />
                    </Button.Icon>
                </Button.Root>
                <Button.Root size="lg">
                    <Button.Icon>
                        <IconSearch />
                    </Button.Icon>
                </Button.Root>
                <Button.Root size="lg" intent="outline">
                    <Button.Icon>
                        <IconSearch />
                    </Button.Icon>
                </Button.Root>
            </div>
        </div>
    )
}
