import type { Meta, StoryObj } from '@storybook/react'

import { Heading } from './heading'

const meta = {
    title: 'Typography/Heading',
    component: Heading,
    tags: ['autodocs'],
    argTypes: {
        size: {
            control: 'select',
            options: ['2xl', 'xl', 'lg', 'base', 'sm'],
        },
    },
} satisfies Meta<typeof Heading>

export default meta
type Story = StoryObj<typeof meta>

export const Sizes = {
    render: () => (
        <div className="flex flex-col gap-3">
            <Heading size="2xl">Heading 2xl</Heading>
            <Heading size="xl">Heading xl</Heading>
            <Heading size="lg">Heading lg</Heading>
            <Heading size="base">Heading base</Heading>
            <Heading size="sm">Heading sm</Heading>
        </div>
    ),
} satisfies Story

export const SemanticLevels = {
    render: () => (
        <div className="flex flex-col gap-3">
            {/* Visual size decoupled from the heading level — pick the tag for document outline */}
            <Heading size="2xl" render={<h1 />}>
                Page title (h1)
            </Heading>
            <Heading size="lg" render={<h2 />}>
                Section (h2)
            </Heading>
            <Heading size="sm" render={<h3 />}>
                Subsection (h3)
            </Heading>
        </div>
    ),
} satisfies Story
