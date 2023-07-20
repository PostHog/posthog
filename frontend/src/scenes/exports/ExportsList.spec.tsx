import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import '@testing-library/jest-dom'

import { BatchExport } from './api'
import { createExportServiceHandlers } from './api-mocks'
import { NestedExportActionButtons, Exports } from './ExportsList'
import { initKeaTests } from '../../test/init'
import { useMocks } from '../../mocks/jest'

jest.setTimeout(20000)

describe('ExportActionButtons', () => {
    it('renders a pause button that can be clicked to pause an export', async () => {
        const exportId = 123
        const name = `test-export-${Math.random().toString(36).substring(7)}`

        const testExports: { [id: number]: BatchExport } = {
            123: {
                id: exportId.toString(),
                name: name,
                team_id: 1,
                status: 'RUNNING',
                paused: false,
                created_at: new Date().toISOString(),
                last_updated_at: new Date().toISOString(),
                interval: 'hour' as const,
                start_at: null,
                end_at: null,
                destination: {
                    type: 'S3',
                    config: {
                        bucket_name: 'my-bucket',
                        region: 'us-east-1',
                        prefix: 'posthog-events',
                        aws_access_key_id: 'accessKeyId',
                        aws_secret_access_key: 'secretAccessKey',
                    },
                },
            },
        }
        const { exports, handlers } = createExportServiceHandlers(testExports)
        useMocks(handlers)
        initKeaTests()

        render(
            <NestedExportActionButtons
                currentTeamId={1}
                export_={exports[exportId]}
                loading={false}
                updateCallback={() => {}}
            />
        )
        const dropdownButton = await waitFor(() => {
            const dropdownButton = screen.getByRole('button', { name: 'more' })
            expect(dropdownButton).toBeInTheDocument()
            return dropdownButton
        })

        userEvent.click(dropdownButton)

        const pauseButton = await waitFor(() => {
            const pauseButton = screen.getByRole('button', { name: 'Pause this active BatchExport' })
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

        const testExports: { [id: number]: BatchExport } = {
            456: {
                id: exportId.toString(),
                name: name,
                team_id: 1,
                status: 'RUNNING',
                paused: true,
                created_at: new Date().toISOString(),
                last_updated_at: new Date().toISOString(),
                interval: 'hour' as const,
                start_at: null,
                end_at: null,
                destination: {
                    type: 'S3',
                    config: {
                        bucket_name: 'my-bucket',
                        region: 'us-east-1',
                        prefix: 'posthog-events',
                        aws_access_key_id: 'accessKeyId',
                        aws_secret_access_key: 'secretAccessKey',
                    },
                },
            },
        }
        const { exports, handlers } = createExportServiceHandlers(testExports)
        useMocks(handlers)
        initKeaTests()

        render(
            <NestedExportActionButtons
                currentTeamId={1}
                export_={exports[exportId]}
                loading={false}
                updateCallback={() => {}}
            />
        )
        const dropdownButton = await waitFor(() => {
            const dropdownButton = screen.getByRole('button', { name: 'more' })
            expect(dropdownButton).toBeInTheDocument()
            return dropdownButton
        })

        userEvent.click(dropdownButton)

        const resumeButton = await waitFor(() => {
            const resumeButton = screen.getByRole('button', { name: 'Resume this paused BatchExport' })
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

        const testExports: { [id: number]: BatchExport } = {
            789: {
                id: exportId.toString(),
                name: name,
                team_id: 1,
                status: 'RUNNING',
                paused: false,
                created_at: new Date().toISOString(),
                last_updated_at: new Date().toISOString(),
                interval: 'hour' as const,
                start_at: null,
                end_at: null,
                destination: {
                    type: 'S3',
                    config: {
                        bucket_name: 'my-bucket',
                        region: 'us-east-1',
                        prefix: 'posthog-events',
                        aws_access_key_id: 'accessKeyId',
                        aws_secret_access_key: 'secretAccessKey',
                    },
                },
            },
        }
        const { exports, handlers } = createExportServiceHandlers(testExports)
        useMocks(handlers)
        initKeaTests()

        render(
            <NestedExportActionButtons
                currentTeamId={1}
                export_={exports[exportId]}
                loading={false}
                updateCallback={() => {}}
            />
        )
        const dropdownButton = await waitFor(() => {
            const dropdownButton = screen.getByRole('button', { name: 'more' })
            expect(dropdownButton).toBeInTheDocument()
            return dropdownButton
        })

        userEvent.click(dropdownButton)

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

describe('Exports', () => {
    it('renders a table with 3 exports', async () => {
        const testExports: { [id: number]: BatchExport } = {
            1: {
                id: '1',
                name: 'test-export-1',
                team_id: 1,
                status: 'RUNNING' as const,
                paused: false,
                created_at: new Date().toISOString(),
                last_updated_at: new Date().toISOString(),
                interval: 'hour' as const,
                start_at: null,
                end_at: null,
                destination: {
                    type: 'S3',
                    config: {
                        bucket_name: 'my-bucket',
                        region: 'us-east-1',
                        prefix: 'posthog-events',
                        aws_access_key_id: 'accessKeyId',
                        aws_secret_access_key: 'secretAccessKey',
                    },
                },
            },
            2: {
                id: '2',
                name: 'test-export-2',
                team_id: 1,
                status: 'RUNNING' as const,
                paused: false,
                created_at: new Date().toISOString(),
                last_updated_at: new Date().toISOString(),
                interval: 'hour' as const,
                start_at: null,
                end_at: null,
                destination: {
                    type: 'S3',
                    config: {
                        bucket_name: 'my-bucket',
                        region: 'us-east-1',
                        prefix: 'posthog-events',
                        aws_access_key_id: 'accessKeyId',
                        aws_secret_access_key: 'secretAccessKey',
                    },
                },
            },
            3: {
                id: '3',
                name: 'test-export-3',
                team_id: 1,
                status: 'RUNNING' as const,
                paused: false,
                created_at: new Date().toISOString(),
                last_updated_at: new Date().toISOString(),
                interval: 'hour' as const,
                start_at: null,
                end_at: null,
                destination: {
                    type: 'S3',
                    config: {
                        bucket_name: 'my-bucket',
                        region: 'us-east-1',
                        prefix: 'posthog-events',
                        aws_access_key_id: 'accessKeyId',
                        aws_secret_access_key: 'secretAccessKey',
                    },
                },
            },
        }

        const { handlers } = createExportServiceHandlers(testExports)
        useMocks(handlers)
        initKeaTests()

        render(<Exports />)

        await waitFor(
            () => {
                const exportsTable = screen.getByRole('table')
                expect(exportsTable).toBeInTheDocument()

                const rows = screen.getAllByRole('row')
                expect(rows).toHaveLength(4)
            },
            { timeout: 5000 }
        )
    })
})
