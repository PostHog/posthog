import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import type { MediaUploadResponse } from '~/types'

import { VariantScreenshotEditor } from './VariantScreenshot'

function ControlledEditor({
    initialMediaIds,
    onChange,
}: {
    initialMediaIds: string[]
    onChange: (mediaIds: string[]) => void
}): JSX.Element {
    const [mediaIds, setMediaIds] = useState(initialMediaIds)
    return (
        <VariantScreenshotEditor
            mediaIds={mediaIds}
            onChange={(newMediaIds) => {
                setMediaIds(newMediaIds)
                onChange(newMediaIds)
            }}
        />
    )
}

describe('VariantScreenshotEditor', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it('keeps a screenshot removed while another one was uploading removed', async () => {
        let finishUpload: (media: MediaUploadResponse) => void = () => {}
        jest.spyOn(api.media, 'upload').mockReturnValue(
            new Promise((resolve) => {
                finishUpload = resolve
            })
        )
        const onChange = jest.fn()
        const { container } = render(<ControlledEditor initialMediaIds={['media-1', 'media-2']} onChange={onChange} />)

        // A GIF skips client-side compression, so it goes straight to the upload API
        fireEvent.change(container.querySelector('input[type="file"]')!, {
            target: { files: [new File(['gif'], 'new.gif', { type: 'image/gif' })] },
        })
        await waitFor(() => expect(api.media.upload).toHaveBeenCalled())

        fireEvent.click(screen.getAllByLabelText('Remove')[1])
        expect(onChange).toHaveBeenLastCalledWith(['media-1'])

        await act(async () => {
            finishUpload({ id: 'media-3', image_location: '/uploaded_media/media-3', name: 'new.gif' })
        })

        expect(onChange).toHaveBeenLastCalledWith(['media-1', 'media-3'])
    })
})
