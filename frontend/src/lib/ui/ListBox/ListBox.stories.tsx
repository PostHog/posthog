import * as AccordionPrimitive from '@radix-ui/react-accordion'
import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { useState } from 'react'

import { ListBox } from './ListBox'

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

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
                <p className="m-0">Focus is handled with keyboard navigation.</p>
                <p>
                    all elements inside (button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])) gain
                    focus when clicked or focused with keyboard.
                </p>
            </div>
            <ListBox
                className="flex flex-col gap-px max-h-[400px] overflow-y-auto border-1 border-dashed border-darkgray p-2"
                {...props}
            >
                <ListBox.Item asChild className="mb-4">
                    <LemonInput
                        fullWidth
                        className="data-[focused=true]:bg-fill-button-tertiary-active aria-[current=true]:bg-fill-button-tertiary-active"
                    />
                </ListBox.Item>
                <ListBox.Item asChild>
                    <LemonButton
                        to="https://www.google.com"
                        targetBlank
                        fullWidth
                        className="data-[focused=true]:bg-fill-button-tertiary-active aria-[current=true]:bg-fill-button-tertiary-active"
                    >
                        Option 1 (Link)
                    </LemonButton>
                </ListBox.Item>
                <ListBox.Item asChild onClick={() => alert('clicked')}>
                    <LemonButton
                        fullWidth
                        className="data-[focused=true]:bg-fill-button-tertiary-active aria-[current=true]:bg-fill-button-tertiary-active"
                    >
                        Option 2 (Clickable)
                    </LemonButton>
                </ListBox.Item>
                <ListBox.Item asChild aria-disabled>
                    <LemonButton
                        fullWidth
                        disabledReason="This is a disabled reason"
                        className="data-[focused=true]:bg-fill-button-tertiary-active aria-[current=true]:bg-fill-button-tertiary-active"
                    >
                        Option 3
                    </LemonButton>
                </ListBox.Item>
                <AccordionPrimitive.Root
                    type="multiple"
                    value={expandedItemIds}
                    onValueChange={(s) => {
                        setExpandedItemIds(s)
                    }}
                    defaultValue={['one']}
                >
                    <AccordionPrimitive.Item value="one" className="flex flex-col w-full">
                        <AccordionPrimitive.Trigger className="flex items-center gap-2 w-full h-8" asChild>
                            <ListBox.Item asChild>
                                <LemonButton
                                    fullWidth
                                    className="data-[focused=true]:bg-fill-button-tertiary-active aria-[current=true]:bg-fill-button-tertiary-active"
                                >
                                    Option 3 (Accordion)
                                </LemonButton>
                            </ListBox.Item>
                        </AccordionPrimitive.Trigger>
                        <AccordionPrimitive.Content className="ml-4">
                            <ListBox.Item asChild>
                                <LemonButton
                                    fullWidth
                                    className="data-[focused=true]:bg-fill-button-tertiary-active aria-[current=true]:bg-fill-button-tertiary-active"
                                >
                                    Option 3 child
                                </LemonButton>
                            </ListBox.Item>
                        </AccordionPrimitive.Content>
                    </AccordionPrimitive.Item>
                </AccordionPrimitive.Root>

                <ListBox.Item asChild>
                    <LemonButton
                        fullWidth
                        className="data-[focused=true]:bg-fill-button-tertiary-active aria-[current=true]:bg-fill-button-tertiary-active"
                    >
                        Option 4
                    </LemonButton>
                </ListBox.Item>
                <ListBox.Item asChild>
                    <LemonButton
                        fullWidth
                        className="data-[focused=true]:bg-fill-button-tertiary-active aria-[current=true]:bg-fill-button-tertiary-active"
                    >
                        Option 5
                    </LemonButton>
                </ListBox.Item>
                <ListBox.Item asChild>
                    <LemonButton
                        fullWidth
                        className="data-[focused=true]:bg-fill-button-tertiary-active aria-[current=true]:bg-fill-button-tertiary-active"
                    >
                        Option 6
                    </LemonButton>
                </ListBox.Item>
                <ListBox.Item asChild>
                    <LemonButton
                        fullWidth
                        className="data-[focused=true]:bg-fill-button-tertiary-active aria-[current=true]:bg-fill-button-tertiary-active"
                    >
                        Option 7
                    </LemonButton>
                </ListBox.Item>
                <ListBox.Item asChild>
                    <LemonButton
                        fullWidth
                        className="data-[focused=true]:bg-fill-button-tertiary-active aria-[current=true]:bg-fill-button-tertiary-active"
                    >
                        Option 8
                    </LemonButton>
                </ListBox.Item>
                <ListBox.Item asChild>
                    <LemonButton
                        fullWidth
                        className="data-[focused=true]:bg-fill-button-tertiary-active aria-[current=true]:bg-fill-button-tertiary-active"
                    >
                        Option 9
                    </LemonButton>
                </ListBox.Item>
                <ListBox.Item asChild>
                    <LemonButton
                        fullWidth
                        className="data-[focused=true]:bg-fill-button-tertiary-active aria-[current=true]:bg-fill-button-tertiary-active"
                    >
                        Option 10
                    </LemonButton>
                </ListBox.Item>
            </ListBox>
        </div>
    )
}

export const Default: Story = BasicTemplate.bind({})
Default.args = {}
