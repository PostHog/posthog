import { IconActivity, IconChevronDown } from '@posthog/icons'
import { Meta, Story } from '@storybook/react'
import { useState } from 'react'

import {
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
} from '../Dropdown/Dropdown'
import { Button } from './Button'

const meta: Meta = {
    title: 'UI/Button',
}
export default meta

export const Default: Story = () => {
    const [showCheckbox1, setShowCheckbox1] = useState(false)
    const [showCheckbox2, setShowCheckbox2] = useState(false)
    const [showCheckbox3, setShowCheckbox3] = useState(false)
    const [radioValue, setRadioValue] = useState('cabbages')

    return (
        <div className="flex flex-col gap-16 items-start token-bg-primary">
            <div className="flex flex-col xs:flex-row gap-4 token-surface-primary p-4">
                <Button intent="primary">Primary</Button>
                <Button intent="primary" disabledReason="This is a disabled reason">
                    Primary Disabled Reason
                </Button>
                <Button intent="primary" active>
                    Primary Active
                </Button>
            </div>

            <div className="flex flex-col xs:flex-row gap-4 token-surface-primary p-4">
                <Button intent="outline">Outline</Button>
                <Button intent="outline" disabledReason="This is a disabled reason">
                    Outline Disabled Reason
                </Button>
                <Button intent="outline" active>
                    Outline Active
                </Button>
            </div>

            <div className="flex flex-col xs:flex-row gap-4 token-surface-primary p-4">
                <Button intent="muted">Muted</Button>
                <Button intent="muted" disabledReason="This is a disabled reason">
                    Muted Disabled Reason
                </Button>
                <Button intent="muted" active>
                    Muted Active
                </Button>
            </div>

            <div className="flex flex-col xs:flex-row gap-4 token-surface-primary p-4">
                <Button intent="muted-darker">Muted Darker</Button>
                <Button intent="muted-darker" disabledReason="This is a disabled reason">
                    Muted Darker Disabled Reason
                </Button>
                <Button intent="muted-darker" active>
                    Muted Darker Active
                </Button>
            </div>

            {/* <div className="h-[42px] flex flex-col xs:flex-row justify-between items-center gap-2 px-2 token-surface-3000-tertiary py-4">
                <Button intent="top-bar-tabs">Top Bar Tabs</Button>
                <Button intent="top-bar-tabs" sideAction={{ to: '/', onClick: () => {}, children: <IconActivity /> }}>
                Top Bar Tabs Side Action 
                </Button>
                <Button intent="top-bar-tabs" active>
                    Top Bar Tabs Active
                </Button>
                <Button intent="top-bar-tabs" disabled>
                    Top Bar Tabs Disabled
                </Button>
                <Button intent="top-bar-tabs" disabledReason="This is a disabled reason">
                    Top Bar Tabs Disabled Reason
                </Button>
            </div> */}

            <div className="flex flex-col xs:flex-row gap-4 token-surface-primary p-4">
                <Button
                    intent="primary"
                    iconRight={<IconChevronDown />}
                    dropdownContent={
                        <DropdownMenuContent side="bottom" align="start" className="min-w-56" loop>
                            <DropdownMenuLabel>Example dropdown</DropdownMenuLabel>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem buttonProps={{ to: '/' }}>Link</DropdownMenuItem>
                            <DropdownMenuItem
                                buttonProps={{ disabledReason: 'This is a disabled reason', tooltipPlacement: 'top' }}
                            >
                                Disabled
                            </DropdownMenuItem>
                            <DropdownMenuItem
                                buttonProps={{
                                    onClick: () => {
                                        alert('clicked')
                                    },
                                }}
                            >
                                On click
                            </DropdownMenuItem>
                            <DropdownMenuItem
                                buttonProps={{
                                    onClick: (e) => {
                                        e.preventDefault()
                                        alert('clicked')
                                    },
                                }}
                            >
                                On click with prevent default
                            </DropdownMenuItem>
                        </DropdownMenuContent>
                    }
                >
                    As a dropdown
                </Button>

                <Button
                    intent="primary"
                    iconRight={<IconChevronDown />}
                    dropdownContent={
                        <DropdownMenuContent side="bottom" align="start" className="min-w-56" loop>
                            <DropdownMenuLabel>Checkboxes</DropdownMenuLabel>
                            <DropdownMenuSeparator />
                            <DropdownMenuCheckboxItem checked={showCheckbox1} onCheckedChange={setShowCheckbox1}>
                                Checkbox 1
                            </DropdownMenuCheckboxItem>
                            <DropdownMenuCheckboxItem
                                checked={showCheckbox2}
                                onCheckedChange={setShowCheckbox2}
                                buttonProps={{ disabledReason: 'This is a disabled reason' }}
                            >
                                Checkbox 2
                            </DropdownMenuCheckboxItem>
                            <DropdownMenuCheckboxItem checked={showCheckbox3} onCheckedChange={setShowCheckbox3}>
                                Checkbox 3
                            </DropdownMenuCheckboxItem>
                        </DropdownMenuContent>
                    }
                >
                    As a dropdown with checkboxes
                </Button>

                <Button
                    intent="primary"
                    iconRight={<IconChevronDown />}
                    dropdownContent={
                        <DropdownMenuContent side="bottom" align="start" className="min-w-56" loop>
                            <DropdownMenuLabel>Radio buttons</DropdownMenuLabel>
                            <DropdownMenuSeparator />
                            <DropdownMenuRadioGroup value={radioValue} onValueChange={setRadioValue}>
                                <DropdownMenuRadioItem value="of">Of</DropdownMenuRadioItem>
                                <DropdownMenuRadioItem value="cabbages">Cabbages</DropdownMenuRadioItem>
                                <DropdownMenuRadioItem
                                    value="kings"
                                    buttonProps={{ disabledReason: 'This is a disabled reason' }}
                                >
                                    & Kings
                                </DropdownMenuRadioItem>
                            </DropdownMenuRadioGroup>
                        </DropdownMenuContent>
                    }
                >
                    As a dropdown with radio buttons
                </Button>
            </div>
            <div className="flex flex-col xs:flex-row gap-4 token-surface-primary p-4">
                <Button
                    intent="primary"
                    sideAction={{
                        to: '/',
                        onClick: () => {},
                        children: <IconChevronDown />,
                    }}
                >
                    Side Action
                </Button>
                <Button
                    intent="outline"
                    sideAction={{
                        to: '/',
                        onClick: () => {},
                        children: <IconActivity />,
                    }}
                >
                    Side Action
                </Button>
                <Button
                    intent="muted"
                    sideAction={{
                        to: '/',
                        onClick: () => {},
                        children: <IconActivity />,
                    }}
                >
                    Side Action
                </Button>
                <Button
                    intent="muted-darker"
                    sideAction={{
                        to: '/',
                        onClick: () => {},
                        children: <IconActivity />,
                    }}
                >
                    Side Action
                </Button>
                <Button
                    intent="top-bar-tabs"
                    sideAction={{
                        to: '/',
                        onClick: () => {},
                        children: <IconActivity />,
                    }}
                >
                    Side Action
                </Button>
            </div>
        </div>
    )
}
