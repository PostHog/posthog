import { DropdownMenuCheckboxItemProps } from '@radix-ui/react-dropdown-menu'
import type { Meta } from '@storybook/react'
import { useState } from 'react'

import { IconChevronRight, IconSearch } from '@posthog/icons'

import { Link } from 'lib/lemon-ui/Link/Link'
import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuItemIndicator,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'

import { ButtonPrimitive } from '../Button/ButtonPrimitives'

const meta = {
    title: 'UI/DropdownMenu',
    component: DropdownMenu,
    tags: ['autodocs'],
} satisfies Meta<typeof DropdownMenu>

export default meta

type Checked = DropdownMenuCheckboxItemProps['checked']

export function Default(): JSX.Element {
    const [radioChoice, setRadioChoice] = useState<'beers' | 'wines' | 'spirits'>('beers')
    const [showStatusBar, setShowStatusBar] = useState<Checked>(true)
    const [showActivityBar, setShowActivityBar] = useState<Checked>(false)
    const [showPanel, setShowPanel] = useState<Checked>(false)

    return (
        <div className="flex gap-4">
            <DropdownMenu>
                <DropdownMenuTrigger asChild>
                    <ButtonPrimitive>
                        <IconSearch />
                        Dropdown
                        <IconChevronRight className="rotate-90 group-data-[state=open]/button-root:rotate-270" />
                    </ButtonPrimitive>
                </DropdownMenuTrigger>

                <DropdownMenuContent loop align="start">
                    <DropdownMenuLabel>Projects</DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem asChild disabled>
                        <Link
                            to="/"
                            buttonProps={{
                                menuItem: true,
                                disabled: true,
                            }}
                        >
                            Link 1 (disabled)
                        </Link>
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                        <Link
                            to="/"
                            buttonProps={{
                                menuItem: true,
                            }}
                        >
                            Link 2
                        </Link>
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuSub>
                        <DropdownMenuSubTrigger asChild>
                            <Link
                                to="/"
                                buttonProps={{
                                    menuItem: true,
                                }}
                            >
                                More options
                                <IconChevronRight className="group-data-[state=open]/button-root:rotate-180" />
                            </Link>
                        </DropdownMenuSubTrigger>
                        <DropdownMenuSubContent>
                            <DropdownMenuItem asChild>
                                <Link
                                    to="/"
                                    buttonProps={{
                                        menuItem: true,
                                    }}
                                >
                                    Sub link 1
                                </Link>
                            </DropdownMenuItem>
                            <DropdownMenuItem asChild>
                                <Link
                                    to="/"
                                    buttonProps={{
                                        menuItem: true,
                                    }}
                                >
                                    Sub link 2
                                </Link>
                            </DropdownMenuItem>
                            <DropdownMenuItem asChild>
                                <Link
                                    to="/"
                                    buttonProps={{
                                        menuItem: true,
                                    }}
                                >
                                    Sub link 3
                                </Link>
                            </DropdownMenuItem>
                        </DropdownMenuSubContent>
                    </DropdownMenuSub>
                </DropdownMenuContent>
            </DropdownMenu>

            <DropdownMenu>
                <DropdownMenuTrigger asChild>
                    <ButtonPrimitive>
                        <IconSearch />
                        Checkboxes
                    </ButtonPrimitive>
                </DropdownMenuTrigger>

                {/* The Dropdown content menu */}
                <DropdownMenuContent loop align="start" className="min-w-[200px]">
                    <DropdownMenuLabel inset>Projects</DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    <DropdownMenuCheckboxItem checked={showStatusBar} onCheckedChange={setShowStatusBar} asChild>
                        <ButtonPrimitive menuItem>
                            <DropdownMenuItemIndicator intent="checkbox" />
                            Status bar
                        </ButtonPrimitive>
                    </DropdownMenuCheckboxItem>
                    <DropdownMenuCheckboxItem
                        checked={showActivityBar}
                        onCheckedChange={setShowActivityBar}
                        disabled
                        asChild
                    >
                        <ButtonPrimitive menuItem>
                            <DropdownMenuItemIndicator intent="checkbox" />
                            Activity bar
                        </ButtonPrimitive>
                    </DropdownMenuCheckboxItem>
                    <DropdownMenuCheckboxItem checked={showPanel} onCheckedChange={setShowPanel} asChild>
                        <ButtonPrimitive menuItem>
                            <DropdownMenuItemIndicator intent="checkbox" />
                            Panel
                        </ButtonPrimitive>
                    </DropdownMenuCheckboxItem>
                </DropdownMenuContent>
            </DropdownMenu>

            <DropdownMenu>
                <DropdownMenuTrigger asChild>
                    <ButtonPrimitive>
                        <IconSearch />
                        Radio group
                    </ButtonPrimitive>
                </DropdownMenuTrigger>

                {/* The Dropdown content menu */}
                <DropdownMenuContent loop align="start" className="min-w-[200px]">
                    <DropdownMenuLabel inset>Projects</DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    <DropdownMenuRadioGroup
                        value={radioChoice}
                        onValueChange={(value) => setRadioChoice(value as 'beers' | 'wines' | 'spirits')}
                    >
                        <DropdownMenuRadioItem value="beers" asChild>
                            <ButtonPrimitive menuItem>
                                <DropdownMenuItemIndicator intent="radio" />
                                Beers
                            </ButtonPrimitive>
                        </DropdownMenuRadioItem>
                        <DropdownMenuRadioItem value="wines" disabled asChild>
                            <ButtonPrimitive menuItem>
                                <DropdownMenuItemIndicator intent="radio" />
                                Wines
                            </ButtonPrimitive>
                        </DropdownMenuRadioItem>
                        <DropdownMenuRadioItem value="spirits" asChild>
                            <ButtonPrimitive menuItem>
                                <DropdownMenuItemIndicator intent="radio" />
                                Spirits
                            </ButtonPrimitive>
                        </DropdownMenuRadioItem>
                    </DropdownMenuRadioGroup>
                </DropdownMenuContent>
            </DropdownMenu>
        </div>
    )
}
