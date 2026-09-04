import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { preflightLogic } from 'lib/logic/preflightLogic'

import { initKeaTests } from '~/test/init'
import {
    AccessControlLevel,
    type DashboardTileIdOrNew,
    DashboardType,
    PreflightStatus,
    QueryBasedInsightModel,
} from '~/types'

import { ImageTileModal } from 'products/dashboards/frontend/components/ImageTile/ImageTileModal'

jest.mock('lib/hooks/useUploadFiles', () => ({
    useUploadFiles: jest.fn(),
}))

const makeDashboard = (body?: string): DashboardType<QueryBasedInsightModel> =>
    ({
        id: 123,
        name: 'Test dashboard',
        description: '',
        pinned: false,
        created_at: '2024-01-01T00:00:00Z',
        created_by: null,
        last_accessed_at: null,
        is_shared: false,
        deleted: false,
        creation_mode: 'default',
        tiles: body
            ? [
                  {
                      id: 1,
                      color: null,
                      layouts: {},
                      text: { body, last_modified_at: '2024-01-01T00:00:00Z' },
                  },
              ]
            : [],
        filters: {},
        tags: [],
        user_access_level: AccessControlLevel.Editor,
    }) as DashboardType<QueryBasedInsightModel>

const firePointerEvent = (
    element: HTMLElement,
    type: 'pointerdown' | 'pointermove' | 'pointerup' | 'pointercancel',
    init: { button?: number; pointerId: number; clientX: number; clientY: number }
): void => {
    const event = new Event(type, { bubbles: true, cancelable: true })
    Object.defineProperties(event, {
        button: { value: init.button ?? 0 },
        pointerId: { value: init.pointerId },
        clientX: { value: init.clientX },
        clientY: { value: init.clientY },
    })
    fireEvent(element, event)
}

describe('ImageTileModal', () => {
    const useUploadFilesMock = jest.mocked(useUploadFiles)

    beforeEach(() => {
        initKeaTests(false)
        preflightLogic.mount()
        preflightLogic.actions.loadPreflightSuccess({ object_storage: true } as PreflightStatus)
        useUploadFilesMock.mockReturnValue({
            setFilesToUpload: jest.fn(),
            filesToUpload: [],
            uploading: false,
        })
        jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        jest.spyOn(lemonToast, 'error').mockImplementation(jest.fn())
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    function renderModal(
        imageTileId: DashboardTileIdOrNew = null,
        body?: string
    ): { onClose: jest.Mock; uploadOptions: Parameters<typeof useUploadFiles>[0] } {
        const onClose = jest.fn()
        render(<ImageTileModal isOpen onClose={onClose} dashboard={makeDashboard(body)} imageTileId={imageTileId} />)

        return {
            onClose,
            uploadOptions: useUploadFilesMock.mock.calls.at(-1)?.[0] as Parameters<typeof useUploadFiles>[0],
        }
    }

    function getDataAttr(dataAttr: string): HTMLElement {
        return document.querySelector(`[data-attr="${dataAttr}"]`) as HTMLElement
    }

    it('requires an image before saving and hides the tile background option', () => {
        renderModal()

        expect(getDataAttr('save-new-image-tile')).toHaveAttribute('aria-disabled', 'true')
        expect(document.querySelector('[data-attr="image-tile-transparent-background"]')).not.toBeInTheDocument()
    })

    it('renders a replacement preview after upload', () => {
        const { uploadOptions } = renderModal()

        act(() => {
            uploadOptions.onUpload?.('https://example.com/portrait.png', 'portrait.png', 'media-id')
        })

        expect(getDataAttr('image-tile-preview-image')).toHaveAttribute('src', 'https://example.com/portrait.png')
        expect(screen.queryByText(/Drag or use arrow keys to reposition the image/)).not.toBeInTheDocument()

        expect(getDataAttr('image-tile-preview-image')).toHaveAttribute('alt', 'Dashboard image')
        expect(getDataAttr('save-new-image-tile')).toHaveAttribute('aria-disabled', 'false')
        expect(getDataAttr('image-tile-transparent-background')).toHaveAttribute('aria-checked', 'true')
    })

    it('opens the file picker when the empty preview is clicked', () => {
        renderModal()

        expect(getDataAttr('image-tile-preview')).toHaveTextContent(
            'Drag and drop an image or click here to upload an image'
        )

        const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
        const click = jest.spyOn(fileInput, 'click')

        fireEvent.click(getDataAttr('image-tile-preview'))

        expect(click).toHaveBeenCalledTimes(1)
    })

    it('opens the file picker when replace image is clicked', () => {
        renderModal(1, '![Image](https://example.com/image.png)')

        const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
        const click = jest.spyOn(fileInput, 'click')

        fireEvent.click(getDataAttr('replace-image-tile-image'))

        expect(click).toHaveBeenCalledTimes(1)
    })

    it('does not open the file picker when an existing image is clicked', () => {
        renderModal(1, '![Image](https://example.com/image.png)')

        const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
        const click = jest.spyOn(fileInput, 'click')

        fireEvent.click(getDataAttr('image-tile-preview'))

        expect(click).not.toHaveBeenCalled()
    })

    it('ignores a second file selection before the first upload starts', () => {
        const setFilesToUpload = jest.fn()
        useUploadFilesMock.mockReturnValue({
            setFilesToUpload,
            filesToUpload: [],
            uploading: false,
        })

        renderModal()

        const input = document.querySelector('input[type="file"]') as HTMLInputElement
        const firstFile = new File(['first'], 'first.png', { type: 'image/png' })
        const secondFile = new File(['second'], 'second.png', { type: 'image/png' })

        fireEvent.change(input, { target: { files: [firstFile] } })
        fireEvent.change(input, { target: { files: [secondFile] } })

        expect(setFilesToUpload).toHaveBeenCalledTimes(1)
        expect(setFilesToUpload).toHaveBeenCalledWith([firstFile])
    })

    it('loads saved image settings and applies them to the preview', () => {
        renderModal(
            1,
            '<img src="https://example.com/landscape.png" alt="Landscape" data-layout="cover" data-position-x="25" data-position-y="75" />'
        )

        expect(getDataAttr('image-tile-preview-image')).toHaveClass('object-cover')
        expect(getDataAttr('image-tile-preview')).toHaveAttribute('aria-label', 'Drag to reposition the image')
        expect(getDataAttr('image-tile-preview-image')).toHaveStyle({
            objectPosition: '25% 75%',
        })
    })

    it('keeps the full image visible in show full image mode', () => {
        renderModal(
            1,
            '<img src="https://example.com/landscape.png" alt="Landscape" data-position-x="25" data-position-y="75" />'
        )

        expect(getDataAttr('image-tile-preview-image')).toHaveClass('object-contain')
        expect(screen.queryByText(/Drag or use arrow keys to reposition the image/)).not.toBeInTheDocument()
    })

    it('updates the image display mode', () => {
        renderModal(1, '![Landscape](https://example.com/landscape.png)')

        fireEvent.click(getDataAttr('image-tile-layout'))
        fireEvent.click(screen.getByText('Fill the tile'))

        expect(getDataAttr('image-tile-preview-image')).toHaveClass('object-cover')
    })

    it('updates the saved image position when the preview is dragged', () => {
        renderModal(1, '<img src="https://example.com/landscape.png" alt="Landscape" data-layout="cover" />')

        const preview = getDataAttr('image-tile-preview')
        const image = getDataAttr('image-tile-preview-image')
        const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
        const click = jest.spyOn(fileInput, 'click')
        expect(image).toHaveClass('pointer-events-none')
        jest.spyOn(preview, 'getBoundingClientRect').mockReturnValue({ width: 200, height: 100 } as DOMRect)
        firePointerEvent(image, 'pointerdown', { button: 0, pointerId: 1, clientX: 100, clientY: 50 })
        firePointerEvent(image, 'pointermove', { pointerId: 1, clientX: 140, clientY: 70 })
        firePointerEvent(image, 'pointerup', { pointerId: 1, clientX: 140, clientY: 70 })
        fireEvent.click(preview)

        expect(getDataAttr('image-tile-preview-image')).toHaveStyle({ objectPosition: '10% 30%' })
        expect(click).not.toHaveBeenCalled()
    })

    it('discards a cancelled drag without opening the file picker', () => {
        renderModal(1, '<img src="https://example.com/landscape.png" alt="Landscape" data-layout="cover" />')

        const preview = getDataAttr('image-tile-preview')
        const image = getDataAttr('image-tile-preview-image')
        const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
        const click = jest.spyOn(fileInput, 'click')
        jest.spyOn(preview, 'getBoundingClientRect').mockReturnValue({ width: 200, height: 100 } as DOMRect)

        firePointerEvent(image, 'pointerdown', { button: 0, pointerId: 1, clientX: 100, clientY: 50 })
        firePointerEvent(image, 'pointermove', { pointerId: 1, clientX: 140, clientY: 70 })
        firePointerEvent(image, 'pointercancel', { pointerId: 1, clientX: 140, clientY: 70 })
        fireEvent.click(preview)

        expect(getDataAttr('image-tile-preview-image')).toHaveStyle({ objectPosition: '50% 50%' })
        expect(click).not.toHaveBeenCalled()
    })

    it('keeps the image position when replacing an image', () => {
        const { uploadOptions } = renderModal(
            1,
            '<img src="https://example.com/landscape.png" alt="Landscape" data-layout="cover" data-position-x="25" data-position-y="75" />'
        )

        act(() => {
            uploadOptions.onUpload?.('https://example.com/replacement.png', 'replacement.png', 'media-id')
        })

        expect(getDataAttr('image-tile-preview-image')).toHaveAttribute('src', 'https://example.com/replacement.png')
        expect(getDataAttr('image-tile-preview-image')).toHaveStyle({
            objectPosition: '25% 75%',
        })
    })

    it('reports upload failure without sending upload details', () => {
        const { uploadOptions } = renderModal()
        const capture = jest.mocked(posthog.capture)
        capture.mockClear()

        act(() => {
            uploadOptions.onError('storage unavailable')
        })

        expect(capture).toHaveBeenCalledWith('dashboard image tile upload failed')
        expect(capture).not.toHaveBeenCalledWith('dashboard image tile upload failed', expect.anything())
        expect(lemonToast.error).toHaveBeenCalledWith('We could not upload that image. Try again.')
    })

    it('shows a safe actionable message for an unsupported image format', () => {
        const { uploadOptions } = renderModal()

        act(() => {
            uploadOptions.onError('This image format is not supported')
        })

        expect(lemonToast.error).toHaveBeenCalledWith('Choose a PNG, JPG, GIF, WebP, or AVIF image.')
        expect(posthog.capture).toHaveBeenCalledWith('dashboard image tile upload failed')
    })

    it('disables save while an upload is in progress', () => {
        useUploadFilesMock.mockReturnValue({
            setFilesToUpload: jest.fn(),
            filesToUpload: [],
            uploading: true,
        })

        renderModal(1, '![Image](https://example.com/image.png)')

        expect(getDataAttr('edit-image-tile')).toHaveAttribute('aria-disabled', 'true')
        expect(getDataAttr('edit-image-tile')).toHaveClass('LemonButton--loading')
        expect(document.querySelector('input[type="file"]')).toBeDisabled()
        expect(getDataAttr('image-tile-preview')).toHaveAttribute('aria-disabled', 'true')
        expect(getDataAttr('image-tile-preview')).toHaveAttribute('tabindex', '-1')
        expect(getDataAttr('image-tile-layout')).toHaveAttribute('aria-disabled', 'true')
    })

    it('rejects dropped files while an upload is in progress', () => {
        const setFilesToUpload = jest.fn()
        useUploadFilesMock.mockReturnValue({
            setFilesToUpload,
            filesToUpload: [],
            uploading: true,
        })

        renderModal(1, '![Image](https://example.com/image.png)')

        fireEvent.drop(getDataAttr('image-tile-preview'), {
            dataTransfer: {
                files: [new File(['image'], 'image.png', { type: 'image/png' })],
                items: [{ kind: 'file', type: 'image/png' }],
            },
        })

        expect(setFilesToUpload).not.toHaveBeenCalled()
    })

    it('prevents cancelling while an upload is in progress', () => {
        const onClose = jest.fn()
        useUploadFilesMock.mockReturnValue({
            setFilesToUpload: jest.fn(),
            filesToUpload: [],
            uploading: true,
        })

        render(
            <ImageTileModal
                isOpen
                onClose={onClose}
                dashboard={makeDashboard('![Image](https://example.com/image.png)')}
                imageTileId={1}
            />
        )

        fireEvent.click(screen.getByText('Cancel'))

        expect(onClose).not.toHaveBeenCalled()
    })

    it('closes when cancel is clicked', () => {
        const { onClose } = renderModal()

        fireEvent.click(screen.getByText('Cancel'))

        expect(onClose).toHaveBeenCalledTimes(1)
    })
})
