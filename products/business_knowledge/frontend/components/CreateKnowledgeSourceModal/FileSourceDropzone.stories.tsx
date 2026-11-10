import type { Meta, StoryObj } from '@storybook/react'

import { FileSourceDropzone } from './FileSourceDropzone'

const meta: Meta<typeof FileSourceDropzone> = {
    title: 'Scenes-App/BusinessKnowledge/FileSourceDropzone',
    component: FileSourceDropzone,
    parameters: { layout: 'padded', viewMode: 'story', testOptions: { snapshotBrowsers: [] } },
    args: {
        onChange: () => undefined,
    },
    decorators: [
        (Story) => (
            <div className="w-120">
                <Story />
            </div>
        ),
    ],
}

export default meta

type Story = StoryObj<typeof FileSourceDropzone>

export const Empty: Story = {
    args: { value: null },
}

export const FileSelected: Story = {
    args: { value: new File(['x'.repeat(248320)], 'refund-policy.pdf', { type: 'application/pdf' }) },
}
