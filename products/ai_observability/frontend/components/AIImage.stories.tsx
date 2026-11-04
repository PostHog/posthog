import type { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'

import { HighlightedJSONViewer } from 'lib/components/HighlightedJSONViewer'

import { AIImage } from './AIImage'

const meta: Meta<typeof AIImage> = {
    title: 'Scenes-App/AI observability/Image preview',
    component: AIImage,
    args: {
        alt: 'Message content',
        className: 'max-w-full max-h-40 rounded',
        fallback: <HighlightedJSONViewer src={{ type: 'image', uri: 'https://example.com/image.png' }} name={null} />,
    },
}
export default meta

type Story = StoryObj<typeof AIImage>

export const LoadedImage: Story = {
    args: { src: '/static/posthog-logo.png' },
    play: async ({ canvasElement }) => {
        await waitFor(() => {
            if (!canvasElement.querySelector('img')?.naturalWidth) {
                throw new Error('The image must finish loading')
            }
        })
    },
}

export const FailedImage: Story = {
    args: { src: 'data:image/png;base64,invalid' },
    play: async ({ canvasElement }) => {
        await waitFor(() => {
            if (
                canvasElement.querySelector('img') ||
                !canvasElement.textContent?.includes('https://example.com/image.png')
            ) {
                throw new Error('The failed image must show its captured URI')
            }
        })
    },
}
