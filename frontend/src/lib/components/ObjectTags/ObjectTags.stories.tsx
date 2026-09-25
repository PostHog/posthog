import type { Meta, StoryObj } from '@storybook/react'

import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { ObjectTags, ObjectTagsProps } from './ObjectTags'

type Story = StoryObj<ObjectTagsProps>
const meta: Meta<ObjectTagsProps> = {
    title: 'Lemon UI/Object Tags',
    component: ObjectTags,
    tags: ['autodocs'],
    render: (props: Partial<ObjectTagsProps>) => {
        return <ObjectTags tags={['one', 'two', 'three']} {...props} />
    },
}
export default meta

export const Default: Story = {
    args: {},
}

export const StaticOnly: Story = {
    args: { staticOnly: true },
}

export const WrapLongTagsInNarrowContainer: Story = {
    render: () => (
        <div className="w-40 rounded border p-2">
            <ObjectTags tags={['support-ticket-tag-with-a-very-long-unbroken-name', 'billing']} staticOnly wrap />
        </div>
    ),
}

// The outlines show the click target: without `shrinkToContent` the inner one spans the whole field.
export const ShrinkToContentInAField: Story = {
    render: () => (
        <div className="flex flex-col gap-1 max-w-160 outline-dashed outline-1">
            <LemonLabel htmlFor="story-tags-trigger">Tags</LemonLabel>
            <ObjectTags
                tags={[]}
                id="story-tags-trigger"
                shrinkToContent
                saving={false}
                onChange={() => {}}
                className="outline-dashed outline-1"
            />
        </div>
    ),
}
