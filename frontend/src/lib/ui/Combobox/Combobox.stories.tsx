import type { Meta } from '@storybook/react'

import { ButtonGroupPrimitive, ButtonPrimitive } from '../Button/ButtonPrimitives'
import { Combobox } from './Combobox'
import { Link } from 'lib/lemon-ui/Link'
import { IconGear } from '@posthog/icons'

const meta = {
    title: 'UI/Combobox',
    component: Combobox,
    tags: ['autodocs'],
} satisfies Meta<typeof Combobox>

export default meta

export function Default(): JSX.Element {
    return (
        <div className="flex gap-4">
            <Combobox>
                <Combobox.Search placeholder="Search this list..." autoFocus />

                <Combobox.Empty>No results found</Combobox.Empty>

                {/* For styling the list items */}
                <Combobox.Content className="max-w-[300px]">
                    {/* responsible for filtering the list items */}
                    {/* can pass in an array of values to filter by */}
                    <Combobox.Group value={['Pineapple', 'belongs on pizza']}>
                        {/* what we actually get as focus */}
                        {/* eslint-disable-next-line no-console */}
                        <Combobox.Item asChild onClick={() => console.log('clicked Pineapple')}>
                            <ButtonPrimitive menuItem>Combobox item: Pineapple</ButtonPrimitive>
                        </Combobox.Item>
                    </Combobox.Group>

                    <Combobox.Group>
                        <ButtonPrimitive menuItem>No value means it will always show</ButtonPrimitive>
                    </Combobox.Group>

                    <div>
                        <ButtonPrimitive menuItem>This will also always show</ButtonPrimitive>
                    </div>

                    <Combobox.Group value={['Banana']}>
                        {/* eslint-disable-next-line no-console */}
                        <Combobox.Item asChild onClick={() => console.log('clicked Banana')}>
                            <ButtonPrimitive menuItem>Combobox item: Pineapple</ButtonPrimitive>
                        </Combobox.Item>
                    </Combobox.Group>

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
                </Combobox.Content>
            </Combobox>

            <div className="max-w-[500px]">
                <p className="font-semibold">This is a combo box</p>
                <ul className="list-disc pl-4">
                    <li>When focused, focus never leaves the search when pressing up or down</li>
                    <li>Combobox.Group is for grouped searchable values, does not hold focus</li>
                    <li>
                        Combobox.Item holds no value, but each Combobox.Item will be available via up down keys, attach
                        your listeners or use as a link
                    </li>
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
