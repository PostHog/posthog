import type { Meta, StoryObj } from '@storybook/react'
import {
    CheckIcon,
    Copy,
    CopyIcon,
    CreditCardIcon,
    EyeOffIcon,
    FileCodeIcon,
    InfoIcon,
    LucideArrowUpRight,
    MailIcon,
    RefreshCcwIcon,
    SearchIcon,
    Star,
    StarIcon,
} from 'lucide-react'
import { useState } from 'react'

import { Field, FieldDescription, FieldGroup, FieldLabel } from './field'
import {
    InputGroup,
    InputGroupAddon,
    InputGroupButton,
    InputGroupInput,
    InputGroupText,
    InputGroupTextarea,
} from './input-group'
import { Kbd } from './kbd'
import { Popover, PopoverContent, PopoverTrigger } from './popover'
import { Spinner } from './spinner'

const meta = {
    title: 'Primitives/Input Group',
    tags: ['autodocs'],
} satisfies Meta<typeof InputGroup>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => (
        <InputGroup className="max-w-xs">
            <InputGroupInput placeholder="Search..." />
            <InputGroupAddon>
                <SearchIcon />
            </InputGroupAddon>
            <InputGroupAddon align="inline-end">12 results</InputGroupAddon>
        </InputGroup>
    ),
} satisfies Story

export const InlineStart: Story = {
    render: () => (
        <Field className="max-w-sm">
            <FieldLabel htmlFor="inline-end-input">Input</FieldLabel>
            <InputGroup>
                <InputGroupInput id="inline-end-input" type="password" placeholder="Enter password" />
                <InputGroupAddon align="inline-start">
                    <SearchIcon />
                </InputGroupAddon>
            </InputGroup>
            <FieldDescription>Icon positioned at the end.</FieldDescription>
        </Field>
    ),
} satisfies Story

export const InlineEnd: Story = {
    render: () => (
        <Field className="max-w-sm">
            <FieldLabel htmlFor="inline-end-input">Input</FieldLabel>
            <InputGroup>
                <InputGroupInput id="inline-end-input" type="password" placeholder="Enter password" />
                <InputGroupAddon align="inline-end">
                    <EyeOffIcon />
                </InputGroupAddon>
            </InputGroup>
            <FieldDescription>Icon positioned at the end.</FieldDescription>
        </Field>
    ),
} satisfies Story

export const BlockStart: Story = {
    render: () => (
        <FieldGroup className="max-w-sm">
      <Field>
        <FieldLabel htmlFor="block-start-input">Input</FieldLabel>
        <InputGroup className="h-auto">
          <InputGroupInput
            id="block-start-input"
            placeholder="Enter your name"
          />
          <InputGroupAddon align="block-start">
            <InputGroupText>Full Name</InputGroupText>
          </InputGroupAddon>
        </InputGroup>
        <FieldDescription>Header positioned above the input.</FieldDescription>
      </Field>
      <Field>
        <FieldLabel htmlFor="block-start-textarea">Textarea</FieldLabel>
        <InputGroup>
          <InputGroupTextarea
            id="block-start-textarea"
            placeholder="console.log('Hello, world!');"
          />
          <InputGroupAddon align="block-start">
            <FileCodeIcon className="text-muted-foreground" />
            <InputGroupText>script.js</InputGroupText>
            <InputGroupButton size="icon-xs" className="ml-auto">
              <CopyIcon />
              <span className="sr-only">Copy</span>
            </InputGroupButton>
          </InputGroupAddon>
        </InputGroup>
        <FieldDescription>
          Header positioned above the textarea.
        </FieldDescription>
      </Field>
    </FieldGroup>
    ),
} satisfies Story
export const BlockEnd: Story = {
    render: () => (
        <FieldGroup className="max-w-sm">
      <Field>
        <FieldLabel htmlFor="block-end-input">Input</FieldLabel>
        <InputGroup className="h-auto">
          <InputGroupInput id="block-end-input" placeholder="Enter amount" />
          <InputGroupAddon align="block-end">
            <InputGroupText>USD</InputGroupText>
          </InputGroupAddon>
        </InputGroup>
        <FieldDescription>Footer positioned below the input.</FieldDescription>
      </Field>
      <Field>
        <FieldLabel htmlFor="block-end-textarea">Textarea</FieldLabel>
        <InputGroup>
          <InputGroupTextarea
            id="block-end-textarea"
            placeholder="Write a comment..."
          />
          <InputGroupAddon align="block-end">
            <InputGroupText>0/280</InputGroupText>
            <InputGroupButton variant="primary" size="sm" className="ml-auto">
              Post
            </InputGroupButton>
          </InputGroupAddon>
        </InputGroup>
        <FieldDescription>
          Footer positioned below the textarea.
        </FieldDescription>
      </Field>
    </FieldGroup>
    ),
} satisfies Story

export const Icons: Story = {
    render: () => (
        <div className="grid w-full max-w-sm gap-6">
            <InputGroup>
                <InputGroupInput placeholder="Search..." />
                <InputGroupAddon>
                    <SearchIcon />
                </InputGroupAddon>
            </InputGroup>
            <InputGroup>
                <InputGroupInput type="email" placeholder="Enter your email" />
                <InputGroupAddon>
                    <MailIcon />
                </InputGroupAddon>
            </InputGroup>
            <InputGroup>
                <InputGroupInput placeholder="Card number" />
                <InputGroupAddon>
                    <CreditCardIcon />
                </InputGroupAddon>
                <InputGroupAddon align="inline-end">
                    <CheckIcon />
                </InputGroupAddon>
            </InputGroup>
            <InputGroup>
                <InputGroupInput placeholder="Card number" />
                <InputGroupAddon align="inline-end">
                    <StarIcon />
                    <InfoIcon />
                </InputGroupAddon>
            </InputGroup>
        </div>
    ),
} satisfies Story

export const Text: Story = {
    render: () => (
        <div className="grid w-full max-w-sm gap-6">
      <InputGroup>
        <InputGroupAddon>
          <InputGroupText>$</InputGroupText>
        </InputGroupAddon>
        <InputGroupInput placeholder="0.00" />
        <InputGroupAddon align="inline-end">
          <InputGroupText>USD</InputGroupText>
        </InputGroupAddon>
      </InputGroup>
      <InputGroup>
        <InputGroupAddon>
          <InputGroupText>https://</InputGroupText>
        </InputGroupAddon>
        <InputGroupInput placeholder="example.com" className="pl-0.5!" />
        <InputGroupAddon align="inline-end">
          <InputGroupText>.com</InputGroupText>
        </InputGroupAddon>
      </InputGroup>
      <InputGroup>
        <InputGroupInput placeholder="Enter your username" />
        <InputGroupAddon align="inline-end">
          <InputGroupText>@company.com</InputGroupText>
        </InputGroupAddon>
      </InputGroup>
      <InputGroup>
        <InputGroupTextarea placeholder="Enter your message" />
        <InputGroupAddon align="block-end">
          <InputGroupText className="text-xs text-muted-foreground">
            120 characters left
          </InputGroupText>
        </InputGroupAddon>
      </InputGroup>
    </div>
    ),
} satisfies Story

export const Buttons: Story = {
    render: () => {
        const [isFavorite, setIsFavorite] = useState(false)
        const [isCopied, setIsCopied] = useState(false)

        return (
            <div className="grid w-full max-w-sm gap-6">
                <InputGroup>
                    <InputGroupInput placeholder="api-asfd-asdkfasdfasdf" readOnly />
                    <InputGroupAddon align="inline-end">
                        <InputGroupButton
                            aria-label="Copy"
                            title="Copy"
                            size="icon-xs"
                            onClick={() => {
                                setIsCopied(true)
                            }}
                        >
                            {isCopied ? <CheckIcon /> : <Copy />}
                        </InputGroupButton>
                    </InputGroupAddon>
                </InputGroup>

                <InputGroup>
                    <Popover>
                        <InputGroupAddon>
                            <PopoverTrigger
                                render={
                                    <InputGroupButton size="icon-xs">
                                        <InfoIcon />
                                    </InputGroupButton>
                                }
                            />
                        </InputGroupAddon>

                        <PopoverContent align="start" className="flex flex-col gap-1 rounded-xl text-sm">
                            <p className="font-medium text-sm">Your connection is not secure.</p>
                            <p className="text-xs">You should not enter any sensitive information on this site.</p>
                        </PopoverContent>
                    </Popover>

                    <InputGroupAddon className="pl-1.5 text-muted-foreground">https://</InputGroupAddon>

                    <InputGroupInput id="input-secure-19" />
                    <InputGroupAddon align="inline-end">
                        <InputGroupButton onClick={() => setIsFavorite(!isFavorite)} size="icon-xs">
                            <Star
                                data-favorite={isFavorite}
                                className="data-[favorite=true]:fill-blue-600 data-[favorite=true]:stroke-blue-600"
                            />
                        </InputGroupButton>
                    </InputGroupAddon>
                </InputGroup>
                <InputGroup>
                    <InputGroupInput placeholder="Type to search..." />
                    <InputGroupAddon align="inline-end">
                        <InputGroupButton variant="primary">Search</InputGroupButton>
                    </InputGroupAddon>
                </InputGroup>
            </div>
        )
    },
} satisfies Story

export const Loading: Story = {
    render: () => {
        return (
            <div className="grid w-full max-w-sm gap-6">
                <InputGroup>
                    <InputGroupAddon align="inline-start">
                        <Spinner />
                    </InputGroupAddon>
                    <InputGroupInput placeholder="Loading..." disabled />
                </InputGroup>
            </div>
        )
    },
} satisfies Story

export const Invalid: Story = {
    render: () => {
        return (
            <div className="grid w-full max-w-sm gap-6">
                <InputGroup>
                    <InputGroupAddon>
                        <MailIcon />
                    </InputGroupAddon>
                    <InputGroupInput placeholder="Oops" aria-invalid="true" />
                </InputGroup>

                <InputGroup>
                    <InputGroupTextarea
                        id="textarea-code-32"
                        placeholder="Textarea with footer"
                        className="min-h-[100px]"
                        aria-invalid="true"
                    />
                    <InputGroupAddon align="block-end" className="border-t border-input/30">
                        <InputGroupText>Line 1, Column 1</InputGroupText>
                        <InputGroupButton size="sm" className="ml-auto" variant="primary">
                            Run <LucideArrowUpRight />
                        </InputGroupButton>
                    </InputGroupAddon>
                </InputGroup>
            </div>
        )
    },
} satisfies Story

export const KBD: Story = {
    render: () => {
        return (
            <div className="grid w-full max-w-sm gap-6">
                <InputGroup>
                    <InputGroupAddon align="inline-end">
                        <Kbd>⌘K</Kbd>
                    </InputGroupAddon>
                    <InputGroupAddon align="inline-start">
                        <SearchIcon className="text-muted-foreground" />
                    </InputGroupAddon>
                    <InputGroupInput placeholder="Search..." />
                </InputGroup>
            </div>
        )
    },
} satisfies Story

export const Textarea: Story = {
    render: () => {
        return (
            <div className="grid w-full max-w-md gap-4">
                <InputGroup>
                    <InputGroupTextarea id="textarea-code-32" placeholder="Normal textarea" className="min-h-[100px]" />
                </InputGroup>

                <InputGroup>
                    <InputGroupTextarea
                        id="textarea-code-32"
                        placeholder="Textarea with footer"
                        className="min-h-[100px]"
                    />
                    <InputGroupAddon align="block-end" className="border-t border-input/30">
                        <InputGroupText>Line 1, Column 1</InputGroupText>
                        <InputGroupButton size="sm" className="ml-auto" variant="primary">
                            Run <LucideArrowUpRight />
                        </InputGroupButton>
                    </InputGroupAddon>
                </InputGroup>

                <InputGroup>
                    <InputGroupTextarea
                        id="textarea-code-32"
                        placeholder="Textarea with header and footer"
                        className="min-h-[100px]"
                    />
                    <InputGroupAddon align="block-end" className="border-t border-input/30">
                        <InputGroupText className="font-mono text-sm">Line 1, Column 1</InputGroupText>
                        <InputGroupButton size="sm" className="ml-auto" variant="primary">
                            Run <LucideArrowUpRight />
                        </InputGroupButton>
                    </InputGroupAddon>

                    <InputGroupAddon align="block-start" className="border-b border-input/30">
                        <InputGroupText className="font-mono font-medium">script.js</InputGroupText>
                        <InputGroupButton className="ml-auto" size="icon-xs">
                            <RefreshCcwIcon />
                        </InputGroupButton>
                        <InputGroupButton size="icon-xs">
                            <Copy />
                        </InputGroupButton>
                    </InputGroupAddon>
                </InputGroup>
            </div>
        )
    },
} satisfies Story
