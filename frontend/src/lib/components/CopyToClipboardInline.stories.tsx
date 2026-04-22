import type { Meta, StoryObj } from '@storybook/react'

import { CopyToClipboardInline, type InlineProps } from './CopyToClipboard'

type Story = StoryObj<InlineProps>
const meta: Meta<InlineProps> = {
    title: 'Lemon UI/Copy To Clipboard Inline',
    component: CopyToClipboardInline,
    tags: ['autodocs'],
    parameters: {
        docs: {
            description: {
                component:
                    'A component that displays text with an inline copy button. Can be used to copy text to clipboard with a single click or allow text selection.',
            },
        },
    },
    argTypes: {
        children: {
            description: 'Text content to display and copy',
        },
        explicitValue: {
            description: 'Alternative value to copy (different from displayed text)',
        },
        description: {
            description: 'Description shown in toast notification when copied',
        },
        selectable: {
            description: 'Makes text selectable instead of copying on click anywhere',
            control: 'boolean',
        },
        isValueSensitive: {
            description: 'Prevents capturing in analytics tools',
            control: 'boolean',
        },
        tooltipMessage: {
            description: 'Custom tooltip message (defaults to "Click to copy")',
        },
        iconPosition: {
            description: 'Position of the copy icon',
            control: 'radio',
            options: ['end', 'start'],
        },
        iconSize: {
            description: 'Size of the copy icon',
            control: 'radio',
            options: ['small', 'xsmall'],
        },
    },
    render: (props) => {
        return (
            <div className="w-[400px]">
                <CopyToClipboardInline {...props} />
            </div>
        )
    },
}
export default meta

export const Default: Story = {
    args: {
        children: 'Click anywhere to copy this text',
    },
}

export const WithDescription: Story = {
    args: {
        children: 'API key: sk-1234567890abcdef',
        description: 'API key',
    },
}

export const Selectable: Story = {
    args: {
        children: 'This text is selectable - click the copy icon to copy',
        selectable: true,
        description: 'Selectable text',
    },
}

export const ExplicitValue: Story = {
    args: {
        children: 'Display text (click to copy different value)',
        explicitValue: 'This is the actual value that gets copied',
        description: 'Hidden value',
    },
}

export const IconPositions: Story = {
    render: () => {
        return (
            <div className="space-y-4">
                <div>
                    <h4 className="mb-2">Icon at end (default)</h4>
                    <CopyToClipboardInline iconPosition="end">Copy this text</CopyToClipboardInline>
                </div>
                <div>
                    <h4 className="mb-2">Icon at start</h4>
                    <CopyToClipboardInline iconPosition="start">Copy this text</CopyToClipboardInline>
                </div>
            </div>
        )
    },
}

export const IconSizes: Story = {
    render: () => {
        return (
            <div className="space-y-4">
                <div>
                    <h4 className="mb-2">Small icon (default)</h4>
                    <CopyToClipboardInline iconSize="small">Copy this text</CopyToClipboardInline>
                </div>
                <div>
                    <h4 className="mb-2">Extra small icon</h4>
                    <CopyToClipboardInline iconSize="xsmall">Copy this text</CopyToClipboardInline>
                </div>
            </div>
        )
    },
}

export const IconOnly: Story = {
    args: {
        explicitValue: 'This value gets copied when clicking the icon',
        description: 'Hidden text',
    },
}
