import { dropKeaFormsValidationErrors } from './exceptionAutocaptureFilters'

describe('dropKeaFormsValidationErrors', () => {
    it('drops $exception events for the kea-forms client-validation error', () => {
        const event = {
            event: '$exception',
            properties: {
                $exception_list: [{ type: 'Error', value: 'Validation Failed' }],
            },
        }
        expect(dropKeaFormsValidationErrors(event)).toBeNull()
    })

    it('passes non-exception events through unchanged', () => {
        const event = { event: '$pageview', properties: { $current_url: '/foo' } }
        expect(dropKeaFormsValidationErrors(event)).toBe(event)
    })

    it.each([
        ['a different message on an Error', { type: 'Error', value: 'Something else failed' }],
        ['the exact message but a non-Error type', { type: 'TypeError', value: 'Validation Failed' }],
    ])('keeps $exception events with %s', (_label, ex) => {
        const event = { event: '$exception', properties: { $exception_list: [ex] } }
        expect(dropKeaFormsValidationErrors(event)).toBe(event)
    })

    it('tolerates missing properties and missing exception list', () => {
        expect(dropKeaFormsValidationErrors({ event: '$exception' })).toEqual({ event: '$exception' })
    })

    it('returns null when handed null (matching posthog-js before_send contract)', () => {
        expect(dropKeaFormsValidationErrors(null)).toBeNull()
    })
})
