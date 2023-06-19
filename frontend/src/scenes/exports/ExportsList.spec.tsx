import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import '@testing-library/jest-dom'

import { createExportServiceHandlers } from './api-mocks'
import { ExportActionButtons } from './ExportsList'
import { initKeaTests } from '../../test/init'
import { useMocks } from '../../mocks/jest'

describe('ExportActionButtons', () => {
    it('renders a pause button that can be clicked to pause an export', async () => {
        const exportId = 123
        const name = `test-export-${Math.random().toString(36).substring(7)}`

        const testExports = {
            123: {
                id: exportId,
                name: name,
                team_id: 1,
                status: 'RUNNING',
                paused: false,
                created_at: new Date().toISOString(),
                last_updated_at: new Date().toISOString(),
            },
        }
        const { exports, handlers } = createExportServiceHandlers(testExports)
        useMocks(handlers)
        initKeaTests()

        render(
            <ExportActionButtons
                currentTeamId={1}
                export_={exports[exportId]}
                loading={false}
                updateCallback={() => {}}
            />
        )

        const pauseButton = await waitFor(() => {
            const pauseButton = screen.getByRole('button', { name: 'Pause this BatchExport' })
            expect(pauseButton).toBeInTheDocument()
            return pauseButton
        })

        userEvent.click(pauseButton)

        await waitFor(() => {
            const [export_] = Object.values(exports).filter((export_: any) => export_.name === name)
            expect(export_).toEqual(
                expect.objectContaining({
                    name,
                    paused: true,
                })
            )
        })
    })

    it('renders a resume button that can be clicked to resume an export', async () => {
        const exportId = 456
        const name = `test-export-${Math.random().toString(36).substring(7)}`

        const testExports = {
            456: {
                id: exportId,
                name: name,
                team_id: 1,
                status: 'RUNNING',
                paused: true,
                created_at: new Date().toISOString(),
                last_updated_at: new Date().toISOString(),
            },
        }
        const { exports, handlers } = createExportServiceHandlers(testExports)
        useMocks(handlers)
        initKeaTests()

        render(
            <ExportActionButtons
                currentTeamId={1}
                export_={exports[exportId]}
                loading={false}
                updateCallback={() => {}}
            />
        )

        const resumeButton = await waitFor(() => {
            const resumeButton = screen.getByRole('button', { name: 'Resume this BatchExport' })
            expect(resumeButton).toBeInTheDocument()
            return resumeButton
        })

        userEvent.click(resumeButton)

        await waitFor(() => {
            const [export_] = Object.values(exports).filter((export_: any) => export_.name === name)
            expect(export_).toEqual(
                expect.objectContaining({
                    name,
                    paused: false,
                })
            )
        })
    })

    it('renders a delete button that can be clicked to delete an export', async () => {
        const exportId = 789
        const name = `test-export-${Math.random().toString(36).substring(7)}`

        const testExports = {
            789: {
                id: exportId,
                name: name,
                team_id: 1,
                status: 'RUNNING',
                paused: false,
                created_at: new Date().toISOString(),
                last_updated_at: new Date().toISOString(),
            },
        }
        const { exports, handlers } = createExportServiceHandlers(testExports)
        useMocks(handlers)
        initKeaTests()

        render(
            <ExportActionButtons
                currentTeamId={1}
                export_={exports[exportId]}
                loading={false}
                updateCallback={() => {}}
            />
        )

        const deleteButton = await waitFor(() => {
            const deleteButton = screen.getByRole('button', { name: 'Permanently delete this BatchExport' })
            expect(deleteButton).toBeInTheDocument()
            return deleteButton
        })

        userEvent.click(deleteButton)

        await waitFor(() => {
            expect(Object.keys(exports).length).toEqual(0)
        })
    })
})
