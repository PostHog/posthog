import type { Meta, StoryObj } from '@storybook/react'

import { RedactedMediaPlaceholder, RedactedMediaPlaceholderProps } from './RedactedMediaPlaceholder'

const meta: Meta = {
    title: 'Scenes-App/AI observability/Redacted media placeholder',
}
export default meta

export const Image: StoryObj<RedactedMediaPlaceholderProps> = {
    render: (args) => <RedactedMediaPlaceholder {...args} />,
    args: { kind: 'image' },
}

export const File: StoryObj<RedactedMediaPlaceholderProps> = {
    render: (args) => <RedactedMediaPlaceholder {...args} />,
    args: { kind: 'file' },
}

export const Audio: StoryObj<RedactedMediaPlaceholderProps> = {
    render: (args) => <RedactedMediaPlaceholder {...args} />,
    args: { kind: 'audio' },
}
