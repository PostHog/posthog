import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic } from 'kea'

import { initKeaTests } from '~/test/init'

import { ChecksTable } from './ChecksTable'
import { dataQualityCheckEditorLogic } from './dataQualityCheckEditorLogic'
import { dataQualityChecksLogic } from './dataQualityChecksLogic'
import { dataQualityChecksHealthList, dataQualityChecksList, dataQualityRunsList } from './generated/api'
import type { DataQualityCheckApi, DataQualitySuiteRunApi } from './generated/api.schemas'
import { CheckTypeEnumApi } from './generated/api.schemas'

jest.mock('./generated/api', () => ({
    dataQualityChecksList: jest.fn(),
    dataQualityChecksHealthList: jest.fn(),
    dataQualityRunsList: jest.fn(),
    dataQualityRunsRetrieve: jest.fn(),
}))

jest.mock('scenes/data-management/database/databaseTableListLogic', () => ({
    databaseTableListLogic: { loadDatabase: jest.fn(() => ({ type: 'load database (mock)' })) },
}))

const PROPS = { subjectType: 'view' as const, subjectId: 'view-1' }

function buildCheck(overrides: Partial<DataQualityCheckApi> = {}): DataQualityCheckApi {
    return {
        id: 'check-1',
        check_type: CheckTypeEnumApi.NotNull,
        column_name: 'customer_id',
        enabled: true,
        severity: 'error',
        last_status: '',
        last_run_at: null,
        config: {},
        tags: [],
        ...overrides,
    } as DataQualityCheckApi
}

describe('ChecksTable', () => {
    afterEach(cleanup)

    async function renderTable(check: DataQualityCheckApi): Promise<ReturnType<typeof dataQualityChecksLogic.build>> {
        ;(dataQualityChecksList as jest.Mock).mockResolvedValue({ results: [check] })
        ;(dataQualityChecksHealthList as jest.Mock).mockResolvedValue([])
        ;(dataQualityRunsList as jest.Mock).mockResolvedValue({ results: [] })
        initKeaTests()
        const logic = dataQualityChecksLogic(PROPS)
        logic.mount()
        render(
            <BindLogic logic={dataQualityCheckEditorLogic} props={{ surface: 'test' }}>
                <ChecksTable {...PROPS} columns={['customer_id']} outputSchema={[]} />
            </BindLogic>
        )
        await screen.findByText('Last status')
        return logic
    }

    it('shows Running and disables Run now while the check runs', async () => {
        const logic = await renderTable(buildCheck())
        logic.actions.setActiveSuiteRun({ id: 'suite-1', status: 'running' } as DataQualitySuiteRunApi, 'check-1')

        expect(await screen.findByText('Running')).toBeInTheDocument()

        await userEvent.click(screen.getByRole('button', { name: /Actions for check/i }))
        expect(await screen.findByRole('menuitem', { name: 'Run now' })).toHaveAttribute('aria-disabled', 'true')
        logic.unmount()
    })

    it('disables opening failing rows until the check has run', async () => {
        const logic = await renderTable(buildCheck({ last_run_at: null }))

        await userEvent.click(screen.getByRole('button', { name: /Actions for check/i }))
        const item = (await screen.findByText(/Open failing rows/)).closest('[role="menuitem"]')
        expect(item).toHaveAttribute('aria-disabled', 'true')
        logic.unmount()
    })
})
