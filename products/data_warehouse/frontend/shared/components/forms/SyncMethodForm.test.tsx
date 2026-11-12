import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { createRef } from 'react'

import { ExternalDataSourceSyncSchema } from '~/types'

import { SyncTypeLabelMap } from '../../../utils'
import {
    SyncMethodForm,
    SyncMethodFormHandle,
    getInitialRadioState,
    getSaveDisabledReason,
    shouldOfferXmin,
} from './SyncMethodForm'

const NO_KEY_REASON = 'Select primary key columns, or use full table replication instead'
const NO_SOURCE_KEY_REASON =
    'This table has no primary key on the source. Add one there, or use full table replication instead'

const baseSchema: ExternalDataSourceSyncSchema = {
    table: 'orders',
    should_sync: false,
    sync_time_of_day: null,
    incremental_field: null,
    incremental_field_type: null,
    sync_type: null,
    incremental_fields: [],
    incremental_available: false,
    append_available: false,
    supports_webhooks: false,
    should_sync_default: false,
    primary_key_columns: null,
    available_columns: [],
    detected_primary_keys: ['id'],
    xmin_available: true,
}

describe('SyncMethodForm', () => {
    it.each([
        ['available', { xmin_available: true }, true],
        ['not available', { xmin_available: false }, false],
        ['webhook-only table', { xmin_available: true, webhook_only: true }, false],
    ])('offers xmin: %s', (_, overrides, expected) => {
        expect(shouldOfferXmin({ ...baseSchema, ...overrides })).toBe(expected)
    })

    it('exposes a label for the xmin sync type', () => {
        expect(SyncTypeLabelMap.xmin).toBe('xmin')
    })

    it.each([
        ['incremental, no key, key required', 'incremental', null, true, true, NO_KEY_REASON],
        ['incremental, no key, source declares its own key', 'incremental', null, false, true, undefined],
        ['incremental, key picked, key required', 'incremental', ['id'], true, true, undefined],
        ['cdc, no key, source declares its own key', 'cdc', null, false, true, NO_SOURCE_KEY_REASON],
        ['xmin, no key, source declares its own key', 'xmin', null, false, true, NO_SOURCE_KEY_REASON],
        ['cdc, source key', 'cdc', ['id'], false, true, undefined],
        ['cdc, no key, new source', 'cdc', null, false, false, undefined],
    ] as const)('requires a merge key: %s', (_, syncType, mergeKey, keyRequired, replicationKeyRequired, expected) => {
        expect(
            getSaveDisabledReason(
                syncType,
                'updated_at',
                null,
                mergeKey ? [...mergeKey] : null,
                keyRequired,
                replicationKeyRequired
            )
        ).toBe(expected)
    })

    it.each([
        ['key resolvable', true, 'incremental'],
        ['keyless with columns known', false, 'append'],
    ])('preselects incremental only when the key resolves: %s', (_, keyResolvable, expected) => {
        expect(getInitialRadioState({ ...baseSchema, xmin_available: false }, true, true, keyResolvable)).toBe(expected)
    })

    it('defaults append-only to a field other than the model pick, which changes on update', () => {
        const onSave = jest.fn()
        render(
            <SyncMethodForm
                schema={{
                    ...baseSchema,
                    sync_type: 'append',
                    incremental_available: true,
                    append_available: true,
                    incremental_fields: [
                        {
                            field: 'fecha_actualizacion',
                            field_type: 'timestamp',
                            label: 'fecha_actualizacion',
                            type: 'timestamp',
                            recommended: true,
                            picked_by_model: true,
                        },
                        { field: 'created_at', field_type: 'timestamp', label: 'created_at', type: 'timestamp' },
                    ],
                    primary_key_columns: ['id'],
                }}
                availableColumns={[]}
                onClose={() => {}}
                onSave={onSave}
            />
        )

        fireEvent.click(screen.getByText('Save'))

        expect(onSave).toHaveBeenCalledWith('append', 'created_at', 'timestamp', null)
        cleanup()
    })

    it.each([
        ['incremental', true],
        ['append', false],
    ] as const)('shows the model note only while %s is the selected method', (syncType, shown) => {
        render(
            <SyncMethodForm
                schema={{
                    ...baseSchema,
                    sync_type: syncType,
                    incremental_available: true,
                    append_available: true,
                    incremental_field: 'fecha_actualizacion',
                    incremental_fields: [
                        {
                            field: 'fecha_actualizacion',
                            field_type: 'timestamp',
                            label: 'fecha_actualizacion',
                            type: 'timestamp',
                            recommended: true,
                            picked_by_model: true,
                            notes: ['Picked by AI from the table and column names.'],
                        },
                        { field: 'created_at', field_type: 'timestamp', label: 'created_at', type: 'timestamp' },
                    ],
                    primary_key_columns: ['id'],
                }}
                availableColumns={[]}
                onClose={() => {}}
                onSave={() => {}}
            />
        )

        expect(screen.queryByText('Picked by AI from the table and column names.') !== null).toBe(shown)
        cleanup()
    })

    describe('shared settings of the keyed methods', () => {
        afterEach(cleanup)

        const renderForm = (
            syncType: ExternalDataSourceSyncSchema['sync_type'],
            { isNewSource = false, incrementalAvailable = true } = {}
        ): HTMLElement =>
            render(
                <SyncMethodForm
                    schema={{
                        ...baseSchema,
                        sync_type: syncType,
                        cdc_available: true,
                        incremental_available: incrementalAvailable,
                        incremental_history_available: true,
                        append_available: true,
                        incremental_field: 'updated_at',
                        incremental_fields: [
                            { field: 'updated_at', field_type: 'datetime', label: 'updated_at', type: 'datetime' },
                        ],
                    }}
                    availableColumns={[{ field: 'id', label: 'id', type: 'integer', nullable: false }]}
                    detectedPrimaryKeys={['id']}
                    primaryKeyDetectionSupported
                    isNewSource={isNewSource}
                    onClose={() => {}}
                    onSave={() => {}}
                />
            ).container

        it.each([
            ['cdc', {}, true, true],
            ['xmin', {}, true, false],
            ['incremental', {}, true, true],
            ['append', {}, false, false],
            ['full_refresh', {}, false, false],
            // New-source setup reads the CDC key from the source itself, so only the output tables show.
            ['cdc', { isNewSource: true }, false, true],
            // A saved incremental table whose source no longer supports incremental has nothing to configure.
            ['incremental', { incrementalAvailable: false }, false, false],
        ] as const)(
            '%s with %o shows the primary key: %s, output tables: %s',
            (syncType, options, showsKey, showsOutputTables) => {
                renderForm(syncType, options)

                expect(screen.queryByText('Primary key') !== null).toBe(showsKey)
                expect(screen.queryByText('Output tables') !== null).toBe(showsOutputTables)
            }
        )

        // The methods render in separate groups, so a per-group name would split them into several keyboard
        // and screen reader groups.
        it('keeps every sync method in one radio group', () => {
            const container = renderForm('cdc')

            const methodNames = ['cdc', 'xmin', 'incremental', 'append', 'full_refresh'].map(
                (method) => container.querySelector<HTMLInputElement>(`input[type="radio"][value="${method}"]`)?.name
            )
            expect(methodNames.every(Boolean)).toBe(true)
            expect(new Set(methodNames).size).toBe(1)
        })
    })

    describe('output tables of an incremental table', () => {
        afterEach(cleanup)

        const renderIncremental = (
            fieldType: 'datetime' | 'integer',
            historyAvailable: boolean,
            onSave: jest.Mock = jest.fn()
        ): HTMLElement => {
            const { container } = render(
                <SyncMethodForm
                    schema={{
                        ...baseSchema,
                        sync_type: 'incremental',
                        incremental_available: true,
                        incremental_history_available: historyAvailable,
                        incremental_field: 'updated_at',
                        incremental_fields: [
                            { field: 'updated_at', field_type: fieldType, label: 'updated_at', type: fieldType },
                        ],
                        primary_key_columns: ['id'],
                    }}
                    availableColumns={[]}
                    onClose={() => {}}
                    onSave={onSave}
                />
            )
            return container
        }

        it.each([
            ['a date or time cursor', 'datetime' as const, true, true, true],
            ['an integer cursor', 'integer' as const, true, true, false],
            ['the organization without the flag', 'datetime' as const, false, false, false],
        ])('offers history for %s', (_, fieldType, historyAvailable, shown, enabled) => {
            const container = renderIncremental(fieldType, historyAvailable)

            expect(screen.queryByText('Output tables') !== null).toBe(shown)
            const historyOnly = container.querySelector('input[value="cdc_only"]')
            expect(historyOnly !== null && !historyOnly.hasAttribute('disabled')).toBe(enabled)
        })

        it('saves the chosen output tables', () => {
            const onSave = jest.fn()
            renderIncremental('datetime', true, onSave)

            fireEvent.click(screen.getByText('Both'))
            fireEvent.click(screen.getByText('Save'))

            expect(onSave).toHaveBeenCalledWith('incremental', 'updated_at', 'datetime', ['id'], 'both', null)
        })
    })

    describe('primary key picker', () => {
        afterEach(cleanup)

        // The API refuses an incremental switch without a merge key whenever it knows the
        // schema's columns. Discovery returning none must not hide the picker that sets one,
        // or the refusal has no remedy.
        it('offers the stored columns when discovery returned none', () => {
            render(
                <SyncMethodForm
                    schema={{
                        ...baseSchema,
                        sync_type: 'incremental',
                        incremental_available: true,
                        incremental_field: 'updated_at',
                        incremental_fields: [
                            { field: 'updated_at', field_type: 'datetime', label: 'updated_at', type: 'datetime' },
                        ],
                        detected_primary_keys: null,
                        available_columns: [{ field: 'order_id', label: 'order_id', type: 'bigint', nullable: false }],
                    }}
                    availableColumns={[]}
                    primaryKeyDetectionSupported
                    onClose={() => {}}
                    onSave={() => {}}
                />
            )

            expect(screen.getByText(/select one or more columns to use as the primary key/i)).toBeInTheDocument()
        })

        // The API refuses to replace a key once data has synced, so a synced key that differs from the source's
        // must block saving in the form instead of failing after the request.
        it.each([
            ['cdc', ['order_key'], true],
            ['xmin', ['order_key'], true],
            ['cdc', ['id'], false],
        ] as const)(
            'switching a synced table to %s with synced key %s blocks saving: %s',
            (syncType, syncedKey, blocked) => {
                const onSaveDisabledReasonChange = jest.fn()
                render(
                    <SyncMethodForm
                        schema={{
                            ...baseSchema,
                            sync_type: 'incremental',
                            cdc_available: true,
                            incremental_available: true,
                            incremental_field: 'updated_at',
                            incremental_fields: [
                                { field: 'updated_at', field_type: 'datetime', label: 'updated_at', type: 'datetime' },
                            ],
                            primary_key_columns: [...syncedKey],
                        }}
                        availableColumns={[{ field: 'id', label: 'id', type: 'integer', nullable: false }]}
                        detectedPrimaryKeys={['id']}
                        primaryKeyDetectionSupported
                        primaryKeyLocked
                        onSaveDisabledReasonChange={onSaveDisabledReasonChange}
                        onClose={() => {}}
                        onSave={() => {}}
                    />
                )

                fireEvent.click(screen.getByText(syncType === 'cdc' ? 'CDC (change data capture)' : 'xmin replication'))

                const reason = onSaveDisabledReasonChange.mock.calls.at(-1)?.[0]
                expect(reason?.includes('Delete the synced data first') ?? false).toBe(blocked)
            }
        )

        // A never-synced table has no stored key, and the API refuses CDC and xmin without one, so the
        // form has to send the key detection found.
        // CDC deletes carry only the source's primary key, and the xmin reader resolves the key from the
        // source, so a key stored by an earlier incremental setup must not reach either.
        it.each([
            ['cdc', null],
            ['xmin', null],
            ['cdc', ['order_key']],
            ['xmin', ['order_key']],
        ] as const)('sends the source key when saving %s with stored key %s', (syncType, storedKey) => {
            const onSave = jest.fn()
            const ref = createRef<SyncMethodFormHandle>()
            render(
                <SyncMethodForm
                    ref={ref}
                    schema={{
                        ...baseSchema,
                        sync_type: null,
                        cdc_available: true,
                        detected_primary_keys: null,
                        primary_key_columns: storedKey ? [...storedKey] : null,
                    }}
                    availableColumns={[{ field: 'id', label: 'id', type: 'integer', nullable: false }]}
                    detectedPrimaryKeys={['id']}
                    primaryKeyDetectionSupported
                    onClose={() => {}}
                    onSave={onSave}
                />
            )

            fireEvent.click(screen.getByText(syncType === 'cdc' ? 'CDC (change data capture)' : 'xmin replication'))
            expect(screen.getByText(/uses the primary key on the source table/i)).toBeInTheDocument()
            act(() => ref.current?.triggerSave())

            expect(onSave).toHaveBeenCalledWith(
                syncType,
                null,
                null,
                ['id'],
                ...(syncType === 'cdc' ? ['consolidated'] : [])
            )
        })
    })
})
