import { InvalidRecordingError } from '../replayer-factory'

describe('InvalidRecordingError', () => {
    it('is an Error subclass with a dedicated name', () => {
        const cause = new DOMException(
            `Failed to execute 'define' on 'CustomElementRegistry': "webview" is not a valid custom element name`,
            'SyntaxError'
        )
        const err = new InvalidRecordingError('Failed to build replayer from snapshots: webview', cause)

        expect(err).toBeInstanceOf(Error)
        expect(err).toBeInstanceOf(InvalidRecordingError)
        expect(err.name).toBe('InvalidRecordingError')
        expect(err.message).toBe('Failed to build replayer from snapshots: webview')
        expect(err.cause).toBe(cause)
    })
})
