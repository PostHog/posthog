import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expectLogic } from 'kea-test-utils'

import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'

import { initKeaTests } from '~/test/init'
import { ExporterFormat } from '~/types'

import { ExportButton } from './ExportButton'

jest.mock('lib/utils/accessControlUtils', () => ({
    ...jest.requireActual('lib/utils/accessControlUtils'),
    getAccessControlDisabledReason: jest.fn(() => null),
}))

const CSV_ITEM = { export_format: ExporterFormat.CSV, export_context: { path: '/api/whatever' } }

describe('ExportButton', () => {
    let logic: ReturnType<typeof exportsLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        logic = exportsLogic()
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    it('runs a browser-side handler instead of asking the server to render the file', async () => {
        const onClick = jest.fn()
        render(<ExportButton items={[{ export_format: ExporterFormat.PNG, onClick }, CSV_ITEM]} />)

        await userEvent.click(screen.getByText('Export'))
        await userEvent.click(screen.getByText('.png'))

        expect(onClick).toHaveBeenCalledTimes(1)
        await expectLogic(logic).toNotHaveDispatchedActions(['startExport'])
    })

    it('still asks the server for a format with no browser-side handler', async () => {
        render(<ExportButton items={[CSV_ITEM]} />)

        await userEvent.click(screen.getByText('Export'))
        await userEvent.click(screen.getByText('.csv'))

        await expectLogic(logic).toDispatchActions(['startExport'])
    })
})
