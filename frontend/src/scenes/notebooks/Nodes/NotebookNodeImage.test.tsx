import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'
import React from 'react'

import { NotebookNodeImageComponent } from './NotebookNodeImage'

// Mock dependencies
jest.mock('lib/hooks/useUploadFiles', () => ({
    uploadFile: jest.fn(() => Promise.resolve({ image_location: 'https://example.com/image.png' })),
}))

jest.mock('lib/lemon-ui/LemonBanner', () => ({
    LemonBanner: ({ children }: { children: React.ReactNode }) => <div data-testid="lemon-banner">{children}</div>,
}))

jest.mock('lib/lemon-ui/Spinner', () => ({
    SpinnerOverlay: () => <div data-testid="spinner">Loading...</div>,
}))

jest.mock('scenes/notebooks/Nodes/NodeWrapper', () => ({
    createPostHogWidgetNode: (config: any) => config,
}))

describe('NotebookNodeImageComponent', () => {
    const mockUpdateAttributes = jest.fn()
    let createObjectURLSpy: jest.SpyInstance
    let revokeObjectURLSpy: jest.SpyInstance

    beforeEach(() => {
        jest.clearAllMocks()
        createObjectURLSpy = jest.spyOn(global.URL, 'createObjectURL').mockReturnValue('blob:mock-url')
        revokeObjectURLSpy = jest.spyOn(global.URL, 'revokeObjectURL').mockImplementation(() => {})
    })

    afterEach(() => {
        cleanup()
        createObjectURLSpy.mockRestore()
        revokeObjectURLSpy.mockRestore()
    })

    it('should create object URL when file is provided', () => {
        const mockFile = new File(['test'], 'test.png', { type: 'image/png' })

        render(<NotebookNodeImageComponent attributes={{ file: mockFile }} updateAttributes={mockUpdateAttributes} />)

        expect(createObjectURLSpy).toHaveBeenCalledWith(mockFile)
    })

    it('should revoke object URL when component unmounts', () => {
        const mockFile = new File(['test'], 'test.png', { type: 'image/png' })

        const { unmount } = render(
            <NotebookNodeImageComponent attributes={{ file: mockFile }} updateAttributes={mockUpdateAttributes} />
        )

        unmount()

        expect(revokeObjectURLSpy).toHaveBeenCalledWith('blob:mock-url')
    })

    it('should revoke old URL and create new one when file changes', () => {
        const mockFile1 = new File(['test1'], 'test1.png', { type: 'image/png' })
        const mockFile2 = new File(['test2'], 'test2.png', { type: 'image/png' })

        // Return different URLs for each call to distinguish them
        createObjectURLSpy.mockReturnValueOnce('blob:mock-url-1').mockReturnValueOnce('blob:mock-url-2')

        const { rerender } = render(
            <NotebookNodeImageComponent attributes={{ file: mockFile1 }} updateAttributes={mockUpdateAttributes} />
        )

        expect(createObjectURLSpy).toHaveBeenCalledTimes(1)

        rerender(
            <NotebookNodeImageComponent attributes={{ file: mockFile2 }} updateAttributes={mockUpdateAttributes} />
        )

        // Cleanup revokes the first URL, then creates a new one for file2
        expect(revokeObjectURLSpy).toHaveBeenCalledWith('blob:mock-url-1')
        expect(createObjectURLSpy).toHaveBeenCalledTimes(2)
    })

    it('should revoke object URL when upload completes (src is set)', () => {
        const mockFile = new File(['test'], 'test.png', { type: 'image/png' })

        const { rerender } = render(
            <NotebookNodeImageComponent attributes={{ file: mockFile }} updateAttributes={mockUpdateAttributes} />
        )

        expect(createObjectURLSpy).toHaveBeenCalledTimes(1)

        // Upload completes: file cleared, src set
        rerender(
            <NotebookNodeImageComponent
                attributes={{
                    file: undefined,
                    src: 'https://example.com/uploaded.png',
                }}
                updateAttributes={mockUpdateAttributes}
            />
        )

        // The effect cleanup should have revoked the blob URL
        expect(revokeObjectURLSpy).toHaveBeenCalledWith('blob:mock-url')
    })

    it('should not create object URL when src is already set', () => {
        render(
            <NotebookNodeImageComponent
                attributes={{ src: 'https://example.com/existing.png' }}
                updateAttributes={mockUpdateAttributes}
            />
        )

        expect(createObjectURLSpy).not.toHaveBeenCalled()
    })
})
