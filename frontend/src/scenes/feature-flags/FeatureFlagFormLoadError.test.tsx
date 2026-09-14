import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'
import posthog from 'posthog-js'

import { FeatureFlagFormLoadError } from './FeatureFlagFormLoadError'

describe('FeatureFlagFormLoadError', () => {
    let captureExceptionSpy: jest.SpyInstance

    beforeEach(() => {
        captureExceptionSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)
    })

    afterEach(() => {
        captureExceptionSpy.mockRestore()
        cleanup()
    })

    // The boundary above stops the error, so nothing else reports it to error tracking.
    it('reports the chunk failure once per mount', () => {
        const error = new TypeError('Failed to fetch dynamically imported module: /static/chunk.js')

        const { rerender } = render(
            <FeatureFlagFormLoadError error={error} teamId={7} onRetry={() => {}} hasUnsavedChanges={true} />
        )
        rerender(<FeatureFlagFormLoadError error={error} teamId={7} onRetry={() => {}} hasUnsavedChanges={true} />)

        expect(captureExceptionSpy).toHaveBeenCalledTimes(1)
        expect(captureExceptionSpy).toHaveBeenCalledWith(error, expect.objectContaining({ chunk_load_error: true }))
    })
})
