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
import { ButtonGroupPrimitive, ButtonPrimitive } from './ButtonPrimitives'

const meta = {
    title: 'UI/Button',
    component: Button.Root,
    tags: ['autodocs'],
} satisfies Meta<typeof Button.Root>

export default meta

export function Default(): JSX.Element {
    return (
        <div className="flex flex-col gap-4 max-w-lg">
            <ButtonPrimitive variant="outline" size="base">
                Button base
            </ButtonPrimitive>

            <ButtonPrimitive variant="outline" size="base">
                <IconSearch />
                Button base
            </ButtonPrimitive>

            <ButtonPrimitive variant="outline" size="base" className="max-w-[100px]">
                <IconSearch />
                <span className="truncate">Button base truncate</span>
            </ButtonPrimitive>

            <ButtonPrimitive variant="outline" size="base" iconOnly>
                <IconSearch />
            </ButtonPrimitive>

            <ButtonGroupPrimitive size="base" variant="outline">
                <ButtonPrimitive
                    onClick={() => {
                        alert('clicked')
                    }}
                >
                    Button1
                </ButtonPrimitive>
                <ButtonPrimitive href="https://google.com">Link</ButtonPrimitive>
                <ButtonPrimitive iconOnly>
                    <IconSearch />
                </ButtonPrimitive>
                <ButtonPrimitive iconOnly>
                    <IconSearch />
                </ButtonPrimitive>
            </ButtonGroupPrimitive>

            <DropdownMenu>
                <DropdownMenuTrigger asChild>
                    <ButtonPrimitive variant="outline" size="base">
                        <IconSearch />
                        is all dropdown
                    </ButtonPrimitive>
                </DropdownMenuTrigger>

                <DropdownMenuContent loop align="start">
                    <DropdownMenuLabel>Section 1</DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive size="base" menuItem>
                            Item 1
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive size="base" menuItem>
                            Item 2
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>

            <DropdownMenu>
                <ButtonGroupPrimitive size="base" variant="outline" fullWidth>
                    <ButtonPrimitive href="https://google.com" menuItem>
                        Link here, dropdown on the right
                    </ButtonPrimitive>
                    <DropdownMenuTrigger asChild>
                        <ButtonPrimitive variant="outline" size="base" iconOnly>
                            <IconSearch />
                        </ButtonPrimitive>
                    </DropdownMenuTrigger>
                </ButtonGroupPrimitive>

                <DropdownMenuContent loop align="start">
                    <DropdownMenuLabel>Section 1</DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive size="base" menuItem>
                            Item 1
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive size="base" menuItem>
                            Item 2
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>

            <DropdownMenu>
                <ButtonGroupPrimitive size="base" variant="default" fullWidth>
                    <ButtonPrimitive href="https://google.com" menuItem>
                        Link here, dropdown on the right
                    </ButtonPrimitive>
                    <DropdownMenuTrigger asChild>
                        <ButtonPrimitive variant="outline" size="base" iconOnly>
                            <IconSearch />
                        </ButtonPrimitive>
                    </DropdownMenuTrigger>
                </ButtonGroupPrimitive>

                <DropdownMenuContent loop align="start">
                    <DropdownMenuLabel>Section 1</DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive size="base" menuItem>
                            Item 1
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive size="base" menuItem>
                            Item 2
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>

            {/*
            <Button.Root intent="outline">
                <Button.Label>Regular button</Button.Label>
            </Button.Root>

            <Button.Root intent="outline" className="max-w-[105px]">
                <Button.Label truncate iconRight>Truncated</Button.Label>
                <Button.Icon end>
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
                <Button.Icon>
                    <IconSearch />
                </Button.Icon>
                <Button.Label iconLeft iconRight>with icon</Button.Label>
                <Button.Icon>
                    <IconSearch />
                </Button.Icon>
            </Button.Root>

            <Button.Root intent="outline" fullWidth onClick={() => {
                alert('clicked')
            }}>
                <Button.Label>full width button</Button.Label>
                <Button.Icon>
                    <IconSearch />
                </Button.Icon>
            </Button.Root>

            <Button.Root intent="outline" fullWidth linkProps={{ to: "https://bing.com" }}>
                <Button.Label>full width link</Button.Label>
                <Button.Icon>
                    <IconSearch />
                </Button.Icon>
            </Button.Root>

            <Button.Root intent="outline">
                <Button.Icon start>
                    <IconSearch />
                </Button.Icon>
                <Button.Label iconLeft iconRight>
                    Icons both sides
                </Button.Label>
                <Button.Icon>
                    <IconSearch />
                </Button.Icon>
            </Button.Root>
            
            <Button.Root intent="outline">
                <Button.IconLink isTrigger to="https://bing.com">
                    <IconSearch />
                </Button.IconLink>
                <Button.Label>
                    Icons links both sides
                </Button.Label>
                <Button.IconLink isTrigger to="https://bing.com">
                    <IconSearch />
                </Button.IconLink>
            </Button.Root>

            <Button.Root intent="outline" linkProps={{ to: "https://bing.com" }}>
                <Button.IconLink isTrigger to="https://google.com">
                    <IconSearch />
                </Button.IconLink>
                <Button.Label>Links</Button.Label>
            </Button.Root>


            <Button.Root intent="outline" onClick={() => {
                alert('clicked main button')
            }}>
                <Button.IconButton 
                    onClick={(e) => {
                        e.preventDefault()
                        e.stopPropagation()
                        alert('clicked left')
                    }} 
                    onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault()
                            e.stopPropagation()
                            alert('clicked left')
                        }
                    }}
                >
                    <IconSearch />
                </Button.IconButton>
                <Button.Label menuItem>menu item with trigger (side action)</Button.Label>
                <Button.IconButton 
                    onClick={(e) => {
                        e.preventDefault()
                        e.stopPropagation()
                        alert('clicked right')
                    }} 
                    onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault()
                            e.stopPropagation()
                            alert('clicked right')
                        }
                    }}
                >
                    <IconSearch />
                </Button.IconButton>
            </Button.Root>

            <DropdownMenu>
                <DropdownMenuTrigger asChild>
                    <Button.Root intent="outline">
                        <Button.Icon>
                            <IconSearch />
                        </Button.Icon>
                    </Button.Root>
                </DropdownMenuTrigger>

                <DropdownMenuContent loop align="start">
                    <DropdownMenuLabel>Projects</DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem asChild>
                        <Button.Root menuItem>
                            <Button.Label>Project 1</Button.Label>
                        </Button.Root>
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                        <Button.Root menuItem>
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
                        <Button.Icon isTrigger showTriggerDivider isTriggerLeft>
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
                        <Button.Icon isTrigger showTriggerDivider>
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
            </Button.Root> */}
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
                    <Button.Label iconLeft>Small button</Button.Label>
                </Button.Root>
                <Button.Root intent="outline" size="sm">
                    <Button.IconLink isTrigger to="https://bing.com">
                        <IconSearch />
                    </Button.IconLink>
                    <Button.Label iconLeft iconRight>
                        menu item with trigger (side action)
                    </Button.Label>
                    <Button.IconLink isTrigger to="https://bing.com">
                        <IconSearch />
                    </Button.IconLink>
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
                    <Button.Label iconLeft>Base button</Button.Label>
                </Button.Root>
                <Button.Root intent="outline" size="base">
                    <Button.IconLink isTrigger to="https://bing.com">
                        <IconSearch />
                    </Button.IconLink>
                    <Button.Label>menu item with trigger (side action)</Button.Label>
                    <Button.IconLink isTrigger to="https://bing.com">
                        <IconSearch />
                    </Button.IconLink>
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
                    <Button.Label iconLeft>Large button</Button.Label>
                </Button.Root>
                <Button.Root intent="outline" size="lg">
                    <Button.IconLink isTrigger to="https://bing.com">
                        <IconSearch />
                    </Button.IconLink>
                    <Button.Label iconLeft iconRight>
                        menu item with trigger (side action)
                    </Button.Label>
                    <Button.IconLink isTrigger to="https://bing.com">
                        <IconSearch />
                    </Button.IconLink>
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
