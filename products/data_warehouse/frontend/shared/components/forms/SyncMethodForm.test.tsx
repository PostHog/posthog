import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { createRef } from 'react'

import { ExternalDataSourceSyncSchema } from '~/types'

import { SyncMethodForm, SyncMethodFormHandle } from './SyncMethodForm'

const mockFlag = { value: true }
jest.mock('lib/hooks/useFeatureFlag', () => ({
    useFeatureFlag: () => mockFlag.value,
}))

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
    beforeEach(() => {
        mockFlag.value = true
    })

    afterEach(() => {
        cleanup()
    })

    const renderForm = (schema: Partial<ExternalDataSourceSyncSchema>, onSave = jest.fn()): { onSave: jest.Mock } => {
        render(<SyncMethodForm schema={{ ...baseSchema, ...schema }} onClose={jest.fn()} onSave={onSave} />)
        return { onSave }
    }

    it('renders the xmin radio when xmin_available and the flag is enabled', () => {
        renderForm({ xmin_available: true })
        expect(screen.getByText('xmin replication')).toBeInTheDocument()
    })

    it('hides the xmin radio when the flag is disabled', () => {
        mockFlag.value = false
        renderForm({ xmin_available: true })
        expect(screen.queryByText('xmin replication')).not.toBeInTheDocument()
    })

    it('hides the xmin radio when the table does not support xmin', () => {
        renderForm({ xmin_available: false })
        expect(screen.queryByText('xmin replication')).not.toBeInTheDocument()
    })

    it('emits sync_type=xmin with no incremental field or cdc table mode on save', () => {
        const onSave = jest.fn()
        const ref = createRef<SyncMethodFormHandle>()
        render(
            <SyncMethodForm
                ref={ref}
                schema={{ ...baseSchema, sync_type: 'xmin' }}
                onClose={jest.fn()}
                onSave={onSave}
            />
        )
        ref.current?.triggerSave()
        expect(onSave).toHaveBeenCalledWith('xmin', null, null, null)
    })
})
