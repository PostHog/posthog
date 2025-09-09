import type { Meta } from '@storybook/react'

import { IconGear, IconPlusSmall } from '@posthog/icons'

import { Link } from 'lib/lemon-ui/Link'

import { ButtonGroupPrimitive, ButtonPrimitive } from '../Button/ButtonPrimitives'
import { DropdownMenuOpenIndicator } from '../DropdownMenu/DropdownMenu'
import {
    PopoverPrimitive,
    PopoverPrimitiveContent,
    PopoverPrimitiveTrigger,
} from '../PopoverPrimitive/PopoverPrimitive'
import { Combobox } from './Combobox'

const meta = {
    title: 'UI/Combobox',
    component: Combobox,
    tags: ['autodocs'],
} satisfies Meta<typeof Combobox>

export default meta

function RenderCombobox(): JSX.Element {
    return (
        <Combobox>
            <Combobox.Search placeholder="Search this list..." autoFocus />

            {/* For styling the list items */}
            <Combobox.Content className="max-w-[300px]">
                <Combobox.Empty>No searchable groups match</Combobox.Empty>

                {/* responsible for filtering the list items */}
                {/* can pass in an array of values to filter by */}
                <Combobox.Group value={['Pineapple', 'belongs on pizza']}>
                    {/* what we actually get as focus */}
                    {/* eslint-disable-next-line no-console */}
                    <Combobox.Item asChild onClick={() => console.log('clicked Pineapple')}>
                        <ButtonPrimitive menuItem>Searchable: Pineapple</ButtonPrimitive>
                    </Combobox.Item>
                </Combobox.Group>

                {/* Groups with no value are "static" and don't affect Empty state */}
                <Combobox.Group>
                    <div className="-mx-1 my-1 h-px bg-border-primary shrink-0" />
                </Combobox.Group>

                <Combobox.Group value={['Banana']}>
                    {/* eslint-disable-next-line no-console */}
                    <Combobox.Item asChild onClick={() => console.log('clicked Banana')}>
                        <ButtonPrimitive menuItem>Searchable: Banana</ButtonPrimitive>
                    </Combobox.Item>
                </Combobox.Group>
                <div className="-mx-1 my-1 h-px bg-border-primary shrink-0" />

                <Combobox.Group value={['projectName']}>
                    <ButtonGroupPrimitive fullWidth className="[&>span]:contents">
                        <Combobox.Item asChild>
                            <ButtonPrimitive menuItem hasSideActionRight className="pr-12" disabled>
                                <span className="truncate">Disabled main button</span>
                            </ButtonPrimitive>
                        </Combobox.Item>
                        <Combobox.Item asChild>
                            <Link
                                buttonProps={{
                                    iconOnly: true,
                                    isSideActionRight: true,
                                }}
                                tooltip="Visit posthog's website"
                                tooltipPlacement="right"
                                to="https://posthog.com"
                            >
                                <IconGear className="text-tertiary" />
                            </Link>
                        </Combobox.Item>
                    </ButtonGroupPrimitive>
                </Combobox.Group>

                <Combobox.Item asChild onClick={() => alert('clicked')}>
                    <ButtonPrimitive menuItem className="shrink-0">
                        <IconPlusSmall className="text-tertiary" />
                        Static: Add item
                    </ButtonPrimitive>
                </Combobox.Item>
            </Combobox.Content>
        </Combobox>
    )
}

export function Default(): JSX.Element {
    return (
        <div className="flex gap-4">
            <RenderCombobox />

            <div className="max-w-[500px]">
                <p className="font-semibold">This is a combo box</p>
                <p className="text-sm text-tertiary mb-2">
                    Try searching for something that doesn't match "Pineapple" or "Banana" to see the Empty state
                </p>
                <ul className="list-disc pl-4">
                    <li>When focused, focus never leaves the search when pressing up or down</li>
                    <li>Combobox.Group is for grouped searchable values, does not hold focus</li>
                    <li>
                        Combobox.Item holds no value, but each Combobox.Item will be available via up down keys, attach
                        your listeners or use as a link
                    </li>
                    <li>
                        Groups with no <code>value</code> prop are considered "static" and always show but don't prevent
                        Empty state
                    </li>
                    <li>Combobox.Empty now shows when no searchable groups match, even if static groups are visible</li>
                    <li>
                        You can see in the last combobox group that the "side action" can get focus via keyboard because
                        it's wrapped in a Combobox.Item
                    </li>
                    <li>
                        Available keyboard listeners: <kbd>down</kbd>, <kbd>up</kbd>, <kbd>home</kbd>, & <kbd>end</kbd>{' '}
                        (provided via <code>Listbox.tsx</code>)
                    </li>
                </ul>
            </div>
        </div>
    )
}

export function InPopover(): JSX.Element {
    return (
        <div className="flex gap-4">
            <PopoverPrimitive>
                <PopoverPrimitiveTrigger asChild>
                    <ButtonPrimitive data-attr="environment-switcher-button" size="sm">
                        Trigger popover
                        <DropdownMenuOpenIndicator />
                    </ButtonPrimitive>
                </PopoverPrimitiveTrigger>
                <PopoverPrimitiveContent align="start">
                    <RenderCombobox />
                </PopoverPrimitiveContent>
            </PopoverPrimitive>
        </div>
    )
}
