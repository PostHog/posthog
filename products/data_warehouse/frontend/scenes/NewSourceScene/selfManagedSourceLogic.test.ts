import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { DataWarehouseTable } from '~/types'

import {
    selfManagedSourceLogic,
    selfManagedTableFormErrors,
    selfManagedTableUpdatePayload,
} from './selfManagedSourceLogic'

const validTable: Partial<DataWarehouseTable> = {
    name: 'stripe_invoices',
    url_pattern: 'https://your-org.s3.amazonaws.com/invoices/*.pqt',
    format: 'Parquet',
    credential: { access_key: 'key', access_secret: 'secret' },
}

describe('selfManagedSourceLogic', () => {
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

    describe('selfManagedTableUpdatePayload', () => {
        it.each([
            ['an uploaded file', null, undefined],
            ['a linked bucket', { access_key: 'key', access_secret: '' }, { access_key: 'key' }],
        ])('keeps the CSV quote handling when saving %s', (_label, credential, expectedCredential) => {
            const payload = selfManagedTableUpdatePayload({
                ...(validTable as DataWarehouseTable),
                format: 'CSVWithNames',
                options: { csv_allow_double_quotes: true },
                credential,
            })

            expect(payload).toEqual({
                name: 'stripe_invoices',
                url_pattern: 'https://your-org.s3.amazonaws.com/invoices/*.pqt',
                format: 'CSVWithNames',
                options: { csv_allow_double_quotes: true },
                ...(expectedCredential ? { credential: expectedCredential } : {}),
            })
        })
    })

    describe('table save failures', () => {
        beforeEach(() => {
            initKeaTests()
            jest.spyOn(lemonToast, 'error').mockImplementation(() => ({ id: 'x' }) as any)
        })

        afterEach(() => {
            jest.restoreAllMocks()
        })

        // A rejected CSV is a validation 400. It must toast the server message without filing an exception.
        it.each([
            { id: 'new', method: 'post', action: 'createTable', status: 400, reported: false },
            { id: 'some-id', method: 'patch', action: 'updateTable', status: 400, reported: false },
            { id: 'new', method: 'post', action: 'createTable', status: 500, reported: true },
        ] as const)(
            '$action with a $status toasts the server message, reported: $reported',
            async ({ id, method, action, status, reported }) => {
                useMocks({
                    get: { '/api/projects/:team_id/warehouse_tables/:id/': () => [200, validTable] },
                    [method]: {
                        '/api/projects/:team_id/warehouse_tables/': () => [status, { detail: 'Check the delimiter.' }],
                        '/api/projects/:team_id/warehouse_tables/:id/': () => [
                            status,
                            { detail: 'Check the delimiter.' },
                        ],
                    },
                })
                const logic = selfManagedSourceLogic({ id })
                logic.mount()

                await expectLogic(logic, () => {
                    logic.actions[action]({ ...validTable, format: 'CSVWithNames' })
                }).toDispatchActions([`${action}Failure`])

                expect(lemonToast.error).toHaveBeenCalledWith(expect.stringContaining('Check the delimiter.'))
                expect(posthog.captureException).toHaveBeenCalledTimes(reported ? 1 : 0)
            }
        )
    })
})
