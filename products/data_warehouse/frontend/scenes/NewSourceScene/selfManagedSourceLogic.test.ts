import { DataWarehouseTable } from '~/types'

import { selfManagedTableFormErrors } from './selfManagedSourceLogic'

const validTable: Partial<DataWarehouseTable> = {
    name: 'stripe_invoices',
    url_pattern: 'https://your-org.s3.amazonaws.com/invoices/*.pqt',
    format: 'Parquet',
    credential: { access_key: 'key', access_secret: 'secret' },
}

describe('selfManagedTableFormErrors', () => {
    // The API serves `credential: null` for tables saved without one (e.g. created by a
    // managed pipeline) — reading through it used to crash the source scene.
    it('validates a table with a null credential instead of throwing', () => {
        const errors = selfManagedTableFormErrors({ ...validTable, credential: null })

        expect(errors.credential).toEqual({
            access_key: 'Please enter an access key.',
            access_secret: 'Please enter an access secret.',
        })
        expect(errors.name).toBeFalsy()
        expect(errors.url_pattern).toBeFalsy()
        expect(errors.format).toBeFalsy()
    })

    it('returns no errors for a fully valid table', () => {
        const errors = selfManagedTableFormErrors(validTable)

        expect(errors.name).toBeFalsy()
        expect(errors.url_pattern).toBeFalsy()
        expect(errors.format).toBeFalsy()
        expect(errors.credential).toEqual({ access_key: false, access_secret: false })
    })

    // The backend rejects any non-https url pattern; these should surface a frontend error instead
    // of falling through to the generic server-side message.
    it.each([
        ['s3://your-org/invoices/*.pqt'],
        ['http://your-org.s3.amazonaws.com/invoices/*.pqt'],
        ['s3a://your-org/invoices/*.pqt'],
        ['your-org.s3.amazonaws.com/invoices/*.pqt'],
    ])('rejects non-https url pattern %s', (url_pattern) => {
        const errors = selfManagedTableFormErrors({ ...validTable, url_pattern })

        expect(errors.url_pattern).toBeTruthy()
    })
})
