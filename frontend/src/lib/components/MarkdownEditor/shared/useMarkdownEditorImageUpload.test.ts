import { renderHook } from '@testing-library/react'

import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { useMarkdownEditorImageUpload } from './useMarkdownEditorImageUpload'

jest.mock('lib/hooks/useUploadFiles', () => ({
    useUploadFiles: jest.fn(() => ({
        setFilesToUpload: jest.fn(),
        filesToUpload: [],
        uploading: false,
    })),
}))

jest.mock('posthog-js', () => ({
    __esModule: true,
    default: { capture: jest.fn() },
}))

jest.mock('lib/lemon-ui/LemonToast', () => ({
    lemonToast: { error: jest.fn() },
}))

const posthog = jest.requireMock('posthog-js').default as { capture: jest.Mock }
const useUploadFilesMock = useUploadFiles as jest.Mock

describe('useMarkdownEditorImageUpload', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('calls setImage and captures analytics on upload', () => {
        const setImage = jest.fn(() => ({ run: () => true }))
        const editor = {
            chain: () => ({
                focus: () => ({
                    setImage,
                }),
            }),
        }

        renderHook(() => useMarkdownEditorImageUpload(editor as never))

        const config = useUploadFilesMock.mock.calls[0][0] as {
            onUpload: (url: string, fileName: string) => void
        }
        config.onUpload('https://example.com/x.png', 'x.png')

        expect(setImage).toHaveBeenCalledWith({ src: 'https://example.com/x.png', alt: 'x.png' })
        expect(posthog.capture).toHaveBeenCalledWith('markdown image uploaded', { name: 'x.png' })
    })

    it('captures failure and toasts on upload error', () => {
        renderHook(() => useMarkdownEditorImageUpload(null))

        const config = useUploadFilesMock.mock.calls[0][0] as { onError: (detail: string) => void }
        config.onError('storage unavailable')

        expect(posthog.capture).toHaveBeenCalledWith('markdown image upload failed', {
            error: 'storage unavailable',
        })
        expect(lemonToast.error).toHaveBeenCalledWith('Error uploading image: storage unavailable')
    })
})
