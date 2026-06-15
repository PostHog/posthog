import type { Meta, StoryObj } from '@storybook/react'

import { Kbd, KbdGroup, KbdText } from './kbd'

const meta = {
    title: 'Primitives/Kbd',
    component: Kbd,
    tags: ['autodocs'],
} satisfies Meta<typeof Kbd>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => {
        return (
            <div className="flex flex-col items-center gap-4">
                <KbdGroup>
                    <Kbd>⌘</Kbd>
                    <Kbd>⇧</Kbd>
                    <Kbd>⌥</Kbd>
                    <Kbd>⌃</Kbd>
                </KbdGroup>
                <KbdGroup>
                    <Kbd>Ctrl</Kbd>
                    <KbdText>+</KbdText>
                    <Kbd>B</Kbd>
                </KbdGroup>
                <KbdGroup>
                    <Kbd>A</Kbd>
                    <KbdText>then</KbdText>
                    <Kbd>B</Kbd>
                </KbdGroup>
            </div>
        )
    },
} satisfies Story