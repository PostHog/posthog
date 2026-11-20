import '@testing-library/jest-dom'
import './react-minified-error'

import { cleanup, render, screen } from '@testing-library/react'

import { ErrorTrackingException } from '../../../types'
import { knownExceptionRegistry } from '../registry'

describe('react minified error', () => {
    afterEach(() => cleanup())

    it.each([
        ['Minified React error #418; visit https://react.dev/errors/418 for the full message'],
        ['React DOM production error #423'],
    ])('links the React docs page for the error code in %s', (value) => {
        const exception: ErrorTrackingException = { id: 'exception-1', type: 'Error', value }

        render(knownExceptionRegistry.match(exception)!.render(exception))

        const code = value.match(/#(\d+)/)![1]
        expect(screen.getByText('React docs').closest('a')).toHaveAttribute('href', `https://react.dev/errors/${code}`)
    })
})
