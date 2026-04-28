import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, DataWarehouseSyncInterval, ExternalDataJobStatus, ExternalDataSource } from '~/types'

import { sourcesDataLogic } from 'products/data_warehouse/frontend/shared/logics/sourcesDataLogic'

import { Modifiers } from './Modifiers'

jest.mock('lib/lemon-ui/LemonSelect', () => ({
    LemonSelect: ({ onChange, options, value }: any): JSX.Element => {
        const flatOptions = options.flatMap((option: any) => ('options' in option ? option.options : option))

        return (
            <select
                value={value === undefined ? '' : String(value)}
                onChange={(event) => {
                    const selectedOption = flatOptions.find(
                        (option: any) => String(option.value) === event.target.value
                    )
                    onChange?.(selectedOption?.value)
                }}
            >
                <option value="">Select a value</option>
                {flatOptions.map((option: any) => (
                    <option key={String(option.value)} value={String(option.value)} disabled={option.disabled}>
                        {option.label}
                    </option>
                ))}
            </select>
        )
    },
}))

describe('Modifiers', () => {
    const mockSourcesResponse = {
        results: [
            {
                id: 'postgres-connection-id',
                source_id: 'source-1',
                connection_id: 'conn-1',
                source_type: 'Postgres',
                status: ExternalDataJobStatus.Running,
                schemas: [],
                prefix: 'analytics-db',
                description: null,
                access_method: 'direct',
                latest_error: null,
                revenue_analytics_config: {
                    enabled: false,
                    include_invoiceless_charges: true,
                },
                sync_frequency: '24hour' as DataWarehouseSyncInterval,
                job_inputs: {},
                user_access_level: AccessControlLevel.Manager,
            },
        ],
        count: 1,
        next: null,
        previous: null,
    } satisfies {
        results: ExternalDataSource[]
        count: number
        next: string | null
        previous: string | null
    }

    beforeEach(() => {
        initKeaTests()
        sourcesDataLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY], {
            [FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY]: false,
        })
    })

    afterEach(() => {
        sourcesDataLogic.unmount()
        jest.restoreAllMocks()
        cleanup()
    })

    it('renders a connection selector for HogQL queries when direct query is enabled', async () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY], {
            [FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY]: true,
        })
        jest.spyOn(api.externalDataSources, 'list').mockResolvedValue(mockSourcesResponse)

        const setQuery = jest.fn()

        render(
            <Provider>
                <Modifiers
                    setQuery={setQuery}
                    query={{ kind: NodeKind.HogQLQuery, query: 'SELECT 1', modifiers: {} }}
                    response={null}
                />
            </Provider>
        )

        expect(screen.getByText('Connection ID:')).toBeInTheDocument()
        await screen.findByRole('option', { name: 'analytics-db (Postgres)' })

        await userEvent.selectOptions(screen.getByLabelText('Connection ID:'), 'postgres-connection-id')

        expect(setQuery).toHaveBeenCalledWith({
            kind: NodeKind.HogQLQuery,
            query: 'SELECT 1',
            modifiers: {},
            connectionId: 'postgres-connection-id',
        })
    })

    it('does not render a connection selector for non-HogQL queries', () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY], {
            [FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY]: false,
        })

        const setQuery = jest.fn()

        render(
            <Provider>
                <Modifiers
                    setQuery={setQuery}
                    query={{ kind: NodeKind.HogQuery, code: 'return 1', modifiers: {} }}
                    response={null}
                />
            </Provider>
        )

        expect(screen.queryByText('Connection ID:')).not.toBeInTheDocument()
    })
})
