import { render, screen } from '@testing-library/react'

import { dayjs } from 'lib/dayjs'

import { ExternalDataSchemaStatus } from '~/types'

import { ModelTableSummary } from './ModelTableSummary'

const baseProps = {
    id: 'node-1',
    table: null,
    source: null,
    schema: null,
    loading: false,
    error: false,
    accessDenied: false,
    onRetry: jest.fn(),
}

describe('ModelTableSummary', () => {
    it('shows PostHog ownership and downstream models for a PostHog table', () => {
        render(<ModelTableSummary {...baseProps} node={{ origin: 'posthog', downstream_count: 1 }} />)

        expect(screen.getByText('Managed by PostHog')).toBeTruthy()
        expect(screen.getByText('PostHog')).toBeTruthy()
        expect(screen.getByText('1 model')).toBeTruthy()
    })

    it('shows source sync metadata for a warehouse table', () => {
        render(
            <ModelTableSummary
                {...baseProps}
                node={{ origin: 'warehouse', downstream_count: 2 }}
                table={{ format: 'Parquet' }}
                source={{ id: 'source-1', source_type: 'Postgres', access_method: 'warehouse' }}
                schema={{
                    id: 'schema-1',
                    status: ExternalDataSchemaStatus.Completed,
                    latest_error: null,
                    last_synced_at: dayjs('2026-09-19T10:00:00Z'),
                    sync_type: 'incremental',
                    sync_frequency: '24hour',
                }}
            />
        )

        expect(screen.getByText('Current status')).toBeTruthy()
        expect(screen.getByText('Completed')).toBeTruthy()
        expect(screen.getByText('Postgres')).toBeTruthy()
        expect(screen.getByText('Incremental')).toBeTruthy()
        expect(screen.getByText('Daily')).toBeTruthy()
        expect(screen.getByText('2 models')).toBeTruthy()
    })
})
