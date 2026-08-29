import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expectLogic } from 'kea-test-utils'

import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

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
        // clearAllMocks keeps any mockReturnValue set by an earlier test, so reset the access default here.
        jest.mocked(getAccessControlDisabledReason).mockReturnValue(null)
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

    it('keeps the menu reachable without export access when a browser format exists, but still gates server formats', async () => {
        jest.mocked(getAccessControlDisabledReason).mockReturnValue('You do not have export access')
        render(<ExportButton items={[{ export_format: ExporterFormat.PNG, onClick: jest.fn() }, CSV_ITEM]} />)

        expect(screen.getByText('Export').closest('button')).toHaveAttribute('aria-disabled', 'false')

        await userEvent.click(screen.getByText('Export'))
        expect(screen.getByText('.png').closest('button')).toHaveAttribute('aria-disabled', 'false')
        expect(screen.getByText('.csv').closest('button')).toHaveAttribute('aria-disabled', 'true')
    })

    it('disables the whole menu without export access when every format renders on the server', () => {
        jest.mocked(getAccessControlDisabledReason).mockReturnValue('You do not have export access')
        render(<ExportButton items={[CSV_ITEM]} />)

        expect(screen.getByText('Export').closest('button')).toHaveAttribute('aria-disabled', 'true')
    })
})
