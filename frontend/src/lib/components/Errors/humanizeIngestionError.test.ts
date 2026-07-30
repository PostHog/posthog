import { humanizeIngestionError } from './humanizeIngestionError'

describe('humanizeIngestionError', () => {
    it('explains a missing exception field without printing the serde error', () => {
        const { message, docsLink } = humanizeIngestionError(
            'Invalid properties on event 0195e5e2-1234-7000-8000-abcdefabcdef, serde error: missing field `type` at line 5 column 13'
        )
        expect(message).toBe(
            `PostHog couldn't read this exception: your SDK left out a required "type" field. Updating to the latest SDK version usually fixes this.`
        )
        // The same serde message covers a missing stacktrace tag, so the copy must
        // not claim the exception itself lacked a type
        expect(message).not.toContain('an exception with no')
        expect(message).not.toContain('serde')
        expect(docsLink).toBeTruthy()
    })

    it('explains a null field', () => {
        expect(
            humanizeIngestionError(
                'Invalid properties on event 0195e5e2-1234-7000-8000-abcdefabcdef, serde error: invalid type: null, expected a string at line 1 column 20'
            ).message
        ).toContain('sent an empty value where a string was expected')
    })

    it.each([
        'Invalid properties on event 0195e5e2-1234-7000-8000-abcdefabcdef, serde error: missing field `$exception_list`',
        'Empty exception list on event 0195e5e2-1234-7000-8000-abcdefabcdef',
    ])('reports missing exception data plainly for %s', (error) => {
        expect(humanizeIngestionError(error).message).toBe(
            "This event didn't include any exception data, so there's no stack trace to show."
        )
    })

    it('leaves non-deserialization warnings untouched', () => {
        const warning = 'Exception steps malformed: step 2 is missing a name'
        expect(humanizeIngestionError(warning)).toEqual({ message: warning })
    })
})
