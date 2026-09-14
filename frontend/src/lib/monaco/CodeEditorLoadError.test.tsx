import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'
import posthog from 'posthog-js'

import { CodeEditorLoadError } from './CodeEditorLoadError'

describe('CodeEditorLoadError', () => {
    let captureExceptionSpy: jest.SpyInstance

    beforeEach(() => {
        captureExceptionSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)
    })

    afterEach(() => {
        captureExceptionSpy.mockRestore()
        cleanup()
    })

    // The boundary above stops the error, so nothing else reports it to error tracking. A capture
    // per render would instead flood it, because a failed editor can re-render many times.
    it('reports the chunk failure once per mount', () => {
        const error = new TypeError('Failed to fetch dynamically imported module: /static/monaco.js')

        const { rerender } = render(<CodeEditorLoadError error={error} onRetry={() => {}} />)
        rerender(<CodeEditorLoadError error={error} onRetry={() => {}} />)

        expect(captureExceptionSpy).toHaveBeenCalledTimes(1)
        expect(captureExceptionSpy).toHaveBeenCalledWith(error, expect.objectContaining({ chunk_load_error: true }))
    })
})
