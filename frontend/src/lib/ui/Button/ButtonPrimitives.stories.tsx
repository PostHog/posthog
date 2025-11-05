import type { Meta } from '@storybook/react'

import { IconGear, IconSearch } from '@posthog/icons'

import { Link } from 'lib/lemon-ui/Link/Link'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'

// import { Button } from './Button'
import { ButtonGroupPrimitive, ButtonPrimitive } from './ButtonPrimitives'

const meta = {
    title: 'UI/ButtonPrimitive',
    component: ButtonPrimitive as any,
    tags: ['autodocs'],
} satisfies Meta<typeof ButtonPrimitive>

export default meta

export function Default(): JSX.Element {
    return (
        <div className="flex flex-col gap-4 max-w-lg">
            <ButtonPrimitive variant="outline" size="base">
                Default Changed
            </ButtonPrimitive>

            <ButtonPrimitive variant="outline" size="base">
                Outline
            </ButtonPrimitive>

            <ButtonPrimitive variant="danger" size="base">
                Danger
            </ButtonPrimitive>

            <ButtonPrimitive size="base" disabled>
                Button base disabled
            </ButtonPrimitive>

            <ButtonPrimitive variant="outline" size="base">
                <IconSearch />
                Button base
            </ButtonPrimitive>

            <ButtonPrimitive variant="outline" size="base" className="max-w-[120px]">
                <IconSearch />
                <span className="truncate">Button base truncate</span>
            </ButtonPrimitive>

            <ButtonPrimitive variant="outline" size="base" iconOnly>
                <IconSearch />
            </ButtonPrimitive>

            <ButtonGroupPrimitive size="base" groupVariant="outline">
                <ButtonPrimitive
                    onClick={() => {
                        alert('clicked')
                    }}
                    tooltip="Tooltip"
                >
                    Button1
                </ButtonPrimitive>
                <Link tooltip="Tooltip" to="https://google.com" target="_blank">
                    Link
                </Link>
                <ButtonPrimitive iconOnly tooltip="Tooltip">
                    <IconSearch />
                </ButtonPrimitive>
                <ButtonPrimitive iconOnly tooltip="Tooltip">
                    <IconSearch />
                </ButtonPrimitive>
            </ButtonGroupPrimitive>

            <ButtonGroupPrimitive size="base" groupVariant="outline">
                <Link
                    buttonProps={{
                        hasSideActionRight: true,
                    }}
                    tooltip="Tooltip"
                    to="#"
                >
                    Side action group
                </Link>
                <Link
                    buttonProps={{
                        iconOnly: true,
                        isSideActionRight: true,
                    }}
                    tooltip="Tooltip"
                    to="#"
                >
                    <IconSearch />
                </Link>
            </ButtonGroupPrimitive>

            <DropdownMenu>
                <DropdownMenuTrigger asChild>
                    <ButtonPrimitive variant="outline" size="base" tooltip="Tooltip">
                        <IconSearch />
                        is all dropdown
                    </ButtonPrimitive>
                </DropdownMenuTrigger>

                <DropdownMenuContent loop align="start">
                    <DropdownMenuGroup>
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
                        <DropdownMenuLabel>Links</DropdownMenuLabel>
                        <ButtonGroupPrimitive menuItem fullWidth>
                            <DropdownMenuItem asChild>
                                <Link
                                    buttonProps={{
                                        menuItem: true,
                                        hasSideActionRight: true,
                                    }}
                                    tooltip="go to google"
                                    tooltipPlacement="right"
                                    to="https://google.com"
                                >
                                    Name
                                </Link>
                            </DropdownMenuItem>
                            <Link
                                buttonProps={{
                                    iconOnly: true,
                                    isSideActionRight: true,
                                }}
                                tooltip="go to bing"
                                tooltipPlacement="right"
                                to="https://bing.com"
                            >
                                <IconGear />
                            </Link>
                        </ButtonGroupPrimitive>
                    </DropdownMenuGroup>
                </DropdownMenuContent>
            </DropdownMenu>

            <DropdownMenu>
                <ButtonGroupPrimitive size="base" groupVariant="outline" fullWidth>
                    <Link
                        buttonProps={{
                            menuItem: true,
                            hasSideActionRight: true,
                        }}
                        to="#"
                    >
                        Link here, dropdown on the right
                    </Link>
                    <DropdownMenuTrigger asChild>
                        <ButtonPrimitive variant="outline" size="base" iconOnly isSideActionRight>
                            <IconSearch />
                        </ButtonPrimitive>
                    </DropdownMenuTrigger>
                </ButtonGroupPrimitive>

                <DropdownMenuContent loop align="start">
                    <DropdownMenuGroup>
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
                    </DropdownMenuGroup>
                </DropdownMenuContent>
            </DropdownMenu>

            <DropdownMenu>
                <ButtonGroupPrimitive size="base" variant="default" fullWidth>
                    <Link
                        buttonProps={{
                            menuItem: true,
                            hasSideActionRight: true,
                        }}
                        to="#"
                    >
                        Link here, dropdown on the right
                    </Link>
                    <DropdownMenuTrigger asChild>
                        <ButtonPrimitive variant="outline" size="base" iconOnly isSideActionRight>
                            <IconSearch />
                        </ButtonPrimitive>
                    </DropdownMenuTrigger>
                </ButtonGroupPrimitive>

                <DropdownMenuContent loop align="start">
                    <DropdownMenuGroup>
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
                    </DropdownMenuGroup>
                </DropdownMenuContent>
            </DropdownMenu>
        </div>
    )
}

export function Sizes(): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-4">
                <ButtonPrimitive size="sm">Small button</ButtonPrimitive>

                <ButtonPrimitive size="sm">
                    <IconSearch />
                    Small button
                </ButtonPrimitive>

                <ButtonPrimitive size="sm" iconOnly>
                    <IconSearch />
                </ButtonPrimitive>
            </div>
            <div className="flex flex-col gap-4">
                <ButtonPrimitive>Base button</ButtonPrimitive>

                <ButtonPrimitive>
                    <IconSearch />
                    Base button
                </ButtonPrimitive>

                <ButtonPrimitive iconOnly>
                    <IconSearch />
                </ButtonPrimitive>
            </div>
            <div className="flex flex-col gap-4">
                <ButtonPrimitive size="lg">Large button</ButtonPrimitive>

                <ButtonPrimitive size="lg">
                    <IconSearch />
                    Large button
                </ButtonPrimitive>

                <ButtonPrimitive size="lg" iconOnly>
                    <IconSearch />
                </ButtonPrimitive>
            </div>
        </div>
    )
}
