import * as AccordionPrimitive from '@radix-ui/react-accordion'
import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useRef, useState } from 'react'

import { Link } from '@posthog/lemon-ui'

import { ButtonPrimitive } from '../Button/ButtonPrimitives'
import { ListBox, ListBoxHandle } from './ListBox'

type Story = StoryObj<typeof ListBox>
const meta: Meta<typeof ListBox> = {
    title: 'UI/List Box',
    component: ListBox,
    args: {},
    tags: ['autodocs'],
}
export default meta

const BasicTemplate: StoryFn<typeof ListBox> = (props: React.ComponentProps<typeof ListBox>) => {
    const [expandedItemIds, setExpandedItemIds] = useState<string[]>([])
    const ref = useRef<ListBoxHandle>(null)

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
                <p className="m-0">Listbox</p>
                <p className="m-0">Wrap any set of elements in a Listbox to enable keyboard navigation.</p>
                <p>
                    (button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])) gain focus when clicked
                    or focused with keyboard, disabled elements are not focusable and skipped.
                </p>
                <ul className="list-inside list-disc">
                    <li>Default (all elements gain 'real' focus)</li>
                    <li>
                        OR virtual focus = true (where local state keeps track of focus allowing you to navigate with
                        keyboard but keep let's say an input focused).
                    </li>
                </ul>
            </div>
            <ListBox
                className="border-1 border-darkgray flex max-h-[400px] flex-col gap-px overflow-y-auto border-dashed p-2"
                {...props}
                ref={ref}
            >
                <ListBox.Item asChild className="mb-4">
                    <input type="text" className="border-primary h-9 rounded-md border p-2" />
                </ListBox.Item>
                <ListBox.Item asChild>
                    <Link
                        to="https://www.google.com"
                        target="_blank"
                        buttonProps={{
                            menuItem: true,
                        }}
                        className="data-[focused=true]:bg-fill-button-tertiary-active aria-[current=true]:bg-fill-button-tertiary-active"
                    >
                        Option 1 (Link)
                    </Link>
                </ListBox.Item>
                <ListBox.Item asChild onClick={() => alert('clicked')}>
                    <ButtonPrimitive
                        menuItem
                        className="data-[focused=true]:bg-fill-button-tertiary-active aria-[current=true]:bg-fill-button-tertiary-active"
                    >
                        Option 2 (Clickable)
                    </ButtonPrimitive>
                </ListBox.Item>
                <ListBox.Item asChild aria-disabled>
                    <ButtonPrimitive
                        menuItem
                        disabled
                        className="data-[focused=true]:bg-fill-button-tertiary-active aria-[current=true]:bg-fill-button-tertiary-active"
                    >
                        Option 3
                    </ButtonPrimitive>
                </ListBox.Item>
                <AccordionPrimitive.Root
                    type="multiple"
                    value={expandedItemIds}
                    onValueChange={(s) => {
                        setExpandedItemIds(s)
                    }}
                    defaultValue={['one']}
                >
                    <AccordionPrimitive.Item value="one" className="flex w-full flex-col">
                        <AccordionPrimitive.Trigger className="flex h-8 w-full items-center gap-2" asChild>
                            <ListBox.Item asChild>
                                <ButtonPrimitive menuItem fullWidth>
                                    Option 3 (Accordion)
                                </ButtonPrimitive>
                            </ListBox.Item>
                        </AccordionPrimitive.Trigger>
                        <AccordionPrimitive.Content className="ml-4">
                            <ListBox.Item asChild>
                                <ButtonPrimitive menuItem fullWidth>
                                    Option 3 child
                                </ButtonPrimitive>
                            </ListBox.Item>
                        </AccordionPrimitive.Content>
                    </AccordionPrimitive.Item>
                </AccordionPrimitive.Root>

                <ListBox.Item asChild>
                    <ButtonPrimitive fullWidth menuItem>
                        Option 4
                    </ButtonPrimitive>
                </ListBox.Item>
            </ListBox>
        </div>
    )
}

export const Default: Story = BasicTemplate.bind({})
Default.args = {
    title: 'List Box',
}

export const VirtualFocus: Story = BasicTemplate.bind({})
VirtualFocus.args = {
    title: 'List Box - Virtual Focus, the input is always focused when navigating with keyboard',
    virtualFocus: true,
}
