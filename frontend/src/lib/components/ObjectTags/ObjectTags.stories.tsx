import type { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

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

export const EditableTagsInNarrowContainer: Story = {
    render: () => (
        <div className="w-40 rounded border p-2" data-attr="narrow-tags-container">
            <ObjectTags
                tags={['first tag', 'a long tag that exceeds the available width', 'third tag']}
                onChange={() => {}}
                saving={false}
                editorFullWidth
            />
        </div>
    ),
    play: async ({ canvasElement }: { canvasElement: HTMLElement }): Promise<void> => {
        const editButton = await within(canvasElement).findByText('Edit tags')
        const container = editButton.closest<HTMLElement>('[data-attr="narrow-tags-container"]')
        if (!container) {
            throw new Error('Expected a narrow tags container')
        }
        await userEvent.click(editButton)
        await waitFor(() => {
            const editor = container.querySelector<HTMLElement>('[data-attr="new-tag-input"]')
            const editorBounds = editor?.getBoundingClientRect()
            const containerBounds = container.getBoundingClientRect()
            if (
                !editorBounds ||
                editorBounds.left < containerBounds.left ||
                editorBounds.right > containerBounds.right
            ) {
                throw new Error('The tag editor must fit inside its container')
            }
        })
    },
}
