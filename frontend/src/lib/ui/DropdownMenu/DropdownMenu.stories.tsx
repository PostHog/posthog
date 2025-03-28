import { IconChevronRight, IconSearch } from '@posthog/icons'
import { DropdownMenuCheckboxItemProps } from '@radix-ui/react-dropdown-menu'
import type { Meta } from '@storybook/react'
import { Button } from 'lib/ui/Button/Button'
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
import { useState } from 'react'

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
                    <Button.Root>
                        <Button.Icon>
                            <IconSearch />
                        </Button.Icon>
                        <Button.Label>Dropdown</Button.Label>
                        <Button.Icon className="rotate-90 group-data-[state=open]/button-root:rotate-270">
                            <IconChevronRight />
                        </Button.Icon>
                    </Button.Root>
                </DropdownMenuTrigger>

                <DropdownMenuContent loop align="start">
                    <DropdownMenuLabel>Projects</DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem asChild disabled>
                        <Button.Root menuItem to="/" disabled>
                            <Button.Label menuItem>Link 1 (disabled)</Button.Label>
                        </Button.Root>
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                        <Button.Root menuItem to="/">
                            <Button.Label menuItem>Link 2</Button.Label>
                        </Button.Root>
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuSub>
                        <DropdownMenuSubTrigger asChild>
                            <Button.Root menuItem to="/">
                                <Button.Label menuItem>More options</Button.Label>
                                <Button.Icon className="group-data-[state=open]/button-root:rotate-180">
                                    <IconChevronRight />
                                </Button.Icon>
                            </Button.Root>
                        </DropdownMenuSubTrigger>
                        <DropdownMenuSubContent>
                            <DropdownMenuItem asChild>
                                <Button.Root menuItem to="/">
                                    <Button.Label menuItem>Sub link 1</Button.Label>
                                </Button.Root>
                            </DropdownMenuItem>
                            <DropdownMenuItem asChild>
                                <Button.Root menuItem to="/">
                                    <Button.Label menuItem>Sub link 2</Button.Label>
                                </Button.Root>
                            </DropdownMenuItem>
                            <DropdownMenuItem asChild>
                                <Button.Root menuItem to="/">
                                    <Button.Label menuItem>Sub link 3</Button.Label>
                                </Button.Root>
                            </DropdownMenuItem>
                        </DropdownMenuSubContent>
                    </DropdownMenuSub>
                </DropdownMenuContent>
            </DropdownMenu>

            <DropdownMenu>
                <DropdownMenuTrigger asChild>
                    <Button.Root>
                        <Button.Icon>
                            <IconSearch />
                        </Button.Icon>
                        <Button.Label>Checkboxes</Button.Label>
                    </Button.Root>
                </DropdownMenuTrigger>

                {/* The Dropdown content menu */}
                <DropdownMenuContent loop align="start" className="min-w-[200px]">
                    <DropdownMenuLabel inset>Projects</DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    <DropdownMenuCheckboxItem checked={showStatusBar} onCheckedChange={setShowStatusBar} asChild>
                        <Button.Root menuItem>
                            <Button.Icon>
                                <DropdownMenuItemIndicator intent="checkbox" />
                            </Button.Icon>
                            <Button.Label menuItem>Status bar</Button.Label>
                        </Button.Root>
                    </DropdownMenuCheckboxItem>
                    <DropdownMenuCheckboxItem
                        checked={showActivityBar}
                        onCheckedChange={setShowActivityBar}
                        disabled
                        asChild
                    >
                        <Button.Root menuItem>
                            <Button.Icon>
                                <DropdownMenuItemIndicator intent="checkbox" />
                            </Button.Icon>
                            <Button.Label menuItem>Activity bar</Button.Label>
                        </Button.Root>
                    </DropdownMenuCheckboxItem>
                    <DropdownMenuCheckboxItem checked={showPanel} onCheckedChange={setShowPanel} asChild>
                        <Button.Root menuItem>
                            <Button.Icon>
                                <DropdownMenuItemIndicator intent="checkbox" />
                            </Button.Icon>
                            <Button.Label menuItem>Panel</Button.Label>
                        </Button.Root>
                    </DropdownMenuCheckboxItem>
                </DropdownMenuContent>
            </DropdownMenu>

            <DropdownMenu>
                <DropdownMenuTrigger asChild>
                    <Button.Root>
                        <Button.Icon>
                            <IconSearch />
                        </Button.Icon>
                        <Button.Label>Radio group</Button.Label>
                    </Button.Root>
                </DropdownMenuTrigger>

                {/* The Dropdown content menu */}
                <DropdownMenuContent loop align="start" className="min-w-[200px]">
                    <DropdownMenuLabel inset>Projects</DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    <DropdownMenuRadioGroup
                        value={radioChoice}
                        onValueChange={(value) => setRadioChoice(value as 'beers' | 'wines' | 'spirits')}
                    >
                        <DropdownMenuRadioItem value="beers">
                            <Button.Root menuItem>
                                <Button.Icon>
                                    <DropdownMenuItemIndicator intent="radio" />
                                </Button.Icon>
                                <Button.Label menuItem>Beers</Button.Label>
                            </Button.Root>
                        </DropdownMenuRadioItem>
                        <DropdownMenuRadioItem value="wines" disabled>
                            <Button.Root menuItem>
                                <Button.Icon>
                                    <DropdownMenuItemIndicator intent="radio" />
                                </Button.Icon>
                                <Button.Label menuItem>Wines</Button.Label>
                            </Button.Root>
                        </DropdownMenuRadioItem>
                        <DropdownMenuRadioItem value="spirits">
                            <Button.Root menuItem>
                                <Button.Icon>
                                    <DropdownMenuItemIndicator intent="radio" />
                                </Button.Icon>
                                <Button.Label menuItem>Spirits</Button.Label>
                            </Button.Root>
                        </DropdownMenuRadioItem>
                    </DropdownMenuRadioGroup>
                </DropdownMenuContent>
            </DropdownMenu>
        </div>
    )
}
