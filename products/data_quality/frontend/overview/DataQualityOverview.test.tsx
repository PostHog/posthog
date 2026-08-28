import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import {
    dataQualityChecksHealthList,
    dataQualityChecksList,
    dataQualityRunsCreate,
    dataQualityRunsRetrieve,
    warehouseSavedQueriesChecksRunsList,
} from 'products/data_quality/frontend/generated/api'
import type { DataQualityOverviewCheckApi } from 'products/data_quality/frontend/generated/api.schemas'

import { DataQualityOverview } from './DataQualityOverview'
import { subjectDisclosureId } from './dataQualityOverviewLogic'

jest.mock('lib/api', () => ({
    __esModule: true,
    default: {},
    ApiConfig: { getCurrentTeamId: jest.fn(() => 1) },
    ApiError: class ApiError extends Error {},
}))

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn(), info: jest.fn(), warning: jest.fn() },
}))

jest.mock('products/data_quality/frontend/generated/api', () => ({
    dataQualityChecksList: jest.fn(),
    dataQualityChecksHealthList: jest.fn(),
    dataQualityRunsCreate: jest.fn(),
    dataQualityRunsRetrieve: jest.fn(),
    warehouseSavedQueriesChecksRunsList: jest.fn(),
    warehouseSavedQueriesChecksDestroy: jest.fn(),
    warehouseTablesChecksDestroy: jest.fn(),
    warehouseSavedQueriesChecksCheckTypesList: jest.fn(),
    warehouseTablesChecksCheckTypesList: jest.fn(),
    warehouseSavedQueriesChecksCreate: jest.fn(),
    warehouseSavedQueriesChecksPartialUpdate: jest.fn(),
    warehouseTablesChecksCreate: jest.fn(),
    warehouseTablesChecksPartialUpdate: jest.fn(),
}))

function buildCheck(
    id: string,
    subject: string,
    overrides: Partial<DataQualityOverviewCheckApi> = {}
): DataQualityOverviewCheckApi {
    return {
        id,
        name: `${subject}_${id}`,
        subject_type: 'view',
        subject_uuid: `uuid-${subject}`,
        subject_name: subject,
        check_type: 'not_null',
        column_name: 'id',
        severity: 'error',
        enabled: true,
        last_status: 'failed',
        last_run_at: null,
        subject_node_id: null,
        subject_source_id: null,
        subject_schema_id: null,
        ...overrides,
    } as DataQualityOverviewCheckApi
}

function failingHealth(subject: string): Record<string, unknown> {
    return {
        subject_type: 'view',
        subject_uuid: `uuid-${subject}`,
        health: 'failing',
        checks_total: 1,
        checks_failing: 1,
    }
}

function queryAll(selector: string): HTMLElement[] {
    return [...document.querySelectorAll<HTMLElement>(selector)]
}

function runSubjectButtons(): HTMLElement[] {
    return queryAll('[data-attr="data-quality-overview-run-subject"]')
}

function isSpinning(button: HTMLElement): boolean {
    return !!button.querySelector('.LemonIcon--spin, [class*="Spinner"]')
}

describe('DataQualityOverview', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        ;(dataQualityChecksList as jest.Mock).mockResolvedValue({
            results: [buildCheck('check-1', 'orders'), buildCheck('check-2', 'customers')],
        })
        ;(dataQualityChecksHealthList as jest.Mock).mockResolvedValue([
            failingHealth('orders'),
            failingHealth('customers'),
        ])
        ;(dataQualityRunsCreate as jest.Mock).mockResolvedValue({
            id: 'suite-1',
            status: 'running',
            trigger: 'manual',
            checks_passed: 0,
            checks_failed: 0,
            checks_errored: 0,
            checks_skipped: 0,
            error: '',
        })
        ;(dataQualityRunsRetrieve as jest.Mock).mockResolvedValue({ id: 'suite-1', status: 'running' })
        ;(warehouseSavedQueriesChecksRunsList as jest.Mock).mockResolvedValue([
            {
                id: 'run-1',
                status: 'failed',
                compiled_query: 'SELECT 1',
                duration_ms: 5,
                observed_value: null,
                failed_row_count: null,
                error: '',
                started_at: null,
            },
        ])
    })

    afterEach(() => {
        cleanup()
    })

    async function renderOverview(): Promise<void> {
        render(<DataQualityOverview />)
        await waitFor(() => expect(runSubjectButtons()).toHaveLength(2))
    }

    it('spins only the subject a run was started from, and disables the rest without a spinner', async () => {
        // The reported regression: one shared loading flag put a spinner on every run control, so a
        // run on one table looked like a run on the whole project.
        await renderOverview()
        fireEvent.click(runSubjectButtons()[0])

        await waitFor(() => expect(isSpinning(runSubjectButtons()[0])).toBe(true))
        const runAll = document.querySelector('[data-attr="data-quality-overview-run-all"]') as HTMLElement
        expect(isSpinning(runSubjectButtons()[1])).toBe(false)
        expect(runSubjectButtons()[1].getAttribute('aria-disabled')).toEqual('true')
        expect(isSpinning(runAll)).toBe(false)
        expect(runAll.getAttribute('aria-disabled')).toEqual('true')
    })

    it('renders no check rows for a collapsed subject', async () => {
        await renderOverview()
        expect(screen.getByText('orders_check-1')).toBeTruthy()

        fireEvent.click(document.getElementById(subjectDisclosureId('view:uuid-orders'))!)

        await waitFor(() => expect(screen.queryByText('orders_check-1')).toBeNull())
        expect(queryAll('[data-attr="data-quality-overview-check-actions"]')).toHaveLength(1)
    })

    it('keeps the disclosure, the subject link and the run action as separate controls', async () => {
        ;(dataQualityChecksList as jest.Mock).mockResolvedValue({
            results: [buildCheck('check-1', 'orders', { subject_node_id: 'node-1' })],
        })
        ;(dataQualityChecksHealthList as jest.Mock).mockResolvedValue([failingHealth('orders')])
        render(<DataQualityOverview />)
        await waitFor(() => expect(runSubjectButtons()).toHaveLength(1))

        const disclosure = queryAll('[data-attr="data-quality-subject-disclosure"]')[0]
        const link = document.querySelector('a[href="/models/node-1"]')!
        expect(disclosure.contains(link)).toBe(false)
        expect(disclosure.contains(runSubjectButtons()[0])).toBe(false)
        expect(disclosure.getAttribute('aria-expanded')).toEqual('true')
        expect(disclosure.getAttribute('aria-controls')).toEqual('data-quality-subject-checks-view:uuid-orders')
    })

    it('renders the subject name as text when it has no page of its own', async () => {
        await renderOverview()

        expect(document.querySelector('a[href^="/models/"]')).toBeNull()
        expect(screen.getAllByText('orders').length).toBeGreaterThan(0)
    })

    it('shows the first-use state when the project has no checks', async () => {
        ;(dataQualityChecksList as jest.Mock).mockResolvedValue({ results: [] })
        ;(dataQualityChecksHealthList as jest.Mock).mockResolvedValue([])
        render(<DataQualityOverview />)

        expect(await screen.findByText('No checks yet')).toBeTruthy()
        expect(screen.queryByText('No checks match these filters.')).toBeNull()
    })

    it('shows a retry rather than an empty page when the first load fails', async () => {
        ;(dataQualityChecksList as jest.Mock).mockRejectedValue(new Error('down'))
        render(<DataQualityOverview />)

        expect(await screen.findByText("Couldn't load data quality checks.")).toBeTruthy()
        expect(screen.queryByText('No checks yet')).toBeNull()
    })

    it('separates the filtered-empty state from the first-use one', async () => {
        await renderOverview()

        fireEvent.change(screen.getByPlaceholderText('Search checks'), { target: { value: 'nothing matches this' } })

        expect(await screen.findByText('No checks match these filters.')).toBeTruthy()
        expect(screen.queryByText('No checks yet')).toBeNull()
        fireEvent.click(screen.getByText('Clear filters'))
        await waitFor(() => expect(runSubjectButtons()).toHaveLength(2))
    })

    it('returns focus to the row action when a delete is canceled', async () => {
        await renderOverview()
        const trigger = queryAll('[data-attr="data-quality-overview-check-actions"]')[0]

        fireEvent.click(trigger)
        fireEvent.click(await screen.findByText('Delete'))
        fireEvent.click(await screen.findByText('Cancel'))

        await waitFor(() => expect(document.activeElement).toBe(trigger))
    })
})
