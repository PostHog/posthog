import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expectLogic } from 'kea-test-utils'
import { type ReactNode } from 'react'

import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'

import { initKeaTests } from '~/test/init'
import { ExporterFormat } from '~/types'

import { SceneExportDropdownMenu } from './SceneExportDropdownMenu'

// Radix relies on pointer events that jsdom does not implement, so the menu renders inline here.
jest.mock('lib/ui/DropdownMenu/DropdownMenu', () => ({
    DropdownMenu: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    DropdownMenuContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    DropdownMenuGroup: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    DropdownMenuItem: ({ children, onClick }: { children: ReactNode; onClick?: () => void }) => (
        <div onClick={onClick}>{children}</div>
    ),
    DropdownMenuTrigger: ({ children }: { children: ReactNode }) => <>{children}</>,
}))

const CSV_ITEM = { format: ExporterFormat.CSV, dataAttr: 'export-csv', context: { path: '/api/whatever' } }

describe('SceneExportDropdownMenu', () => {
    let logic: ReturnType<typeof exportsLogic.build>

    beforeEach(() => {
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
        render(
            <SceneExportDropdownMenu
                dropdownMenuItems={[{ format: ExporterFormat.PNG, dataAttr: 'export-png', onClick }, CSV_ITEM]}
            />
        )

        await userEvent.click(screen.getByText('.png'))

        expect(onClick).toHaveBeenCalledTimes(1)
        await expectLogic(logic).toNotHaveDispatchedActions(['startExport'])
    })

    it('still asks the server for a format with no browser-side handler', async () => {
        render(<SceneExportDropdownMenu dropdownMenuItems={[CSV_ITEM]} />)

        await userEvent.click(screen.getByText('.csv'))

        await expectLogic(logic).toDispatchActions(['startExport'])
    })
})
