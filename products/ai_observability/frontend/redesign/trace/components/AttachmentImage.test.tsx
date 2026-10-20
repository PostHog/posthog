import '@testing-library/jest-dom'

import { fireEvent, render, waitFor } from '@testing-library/react'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { AttachmentImage } from './AttachmentImage'

describe('AttachmentImage', () => {
    beforeEach(() => initKeaTests())

    it.each(['load', 'error'] as const)('reports blob image %s telemetry', async (event) => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        try {
            const hash = (event === 'load' ? 'c' : 'd').repeat(64)
            const { container } = render(
                <AttachmentImage url={`/api/projects/7/ai_blob/v1/sha256/${hash}`} alt="Attached image" />
            )
            fireEvent[event](container.querySelector('img')!)
            await waitFor(() =>
                expect(capture).toHaveBeenCalledWith(
                    'llma ai blob render',
                    expect.objectContaining({
                        outcome: event === 'load' ? 'success' : 'error',
                        media_kind: 'image',
                    })
                )
            )
        } finally {
            capture.mockRestore()
        }
    })

    it('preserves the source link when an image cannot load, and retries new sources', () => {
        const url = 'https://example.com/image.png'
        const { container, rerender } = render(<AttachmentImage url={url} alt="Attached image" />)
        fireEvent.error(container.querySelector('img')!)
        expect(container.querySelector('img')).toBeNull()
        expect(container.textContent).toContain(url)
        expect(container.querySelector('a')).toHaveAttribute('href', url)
        rerender(<AttachmentImage url="https://example.com/second.png" alt="Attached image" />)
        expect(container.querySelector('img')).toHaveAttribute('src', 'https://example.com/second.png')
    })
})
