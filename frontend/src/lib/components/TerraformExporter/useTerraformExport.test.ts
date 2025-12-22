import { renderHook, waitFor } from '@testing-library/react'
import posthog from 'posthog-js'

import api from '~/lib/api'

import * as dashboardHclExporter from './dashboardHclExporter'
import * as insightHclExporter from './insightHclExporter'
import { TerraformExportResource, useTerraformExport } from './useTerraformExport'

jest.mock('~/lib/api')
jest.mock('posthog-js')

const mockedApi = api as jest.Mocked<typeof api>

describe('useTerraformExport', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        mockedApi.alerts = {
            list: jest.fn().mockResolvedValue({ results: [] }),
        } as any
        mockedApi.hogFunctions = {
            listForAlert: jest.fn().mockResolvedValue({ results: [] }),
        } as any
    })

    describe('error handling', () => {
        it('catches generateInsightHCL errors and provides descriptive message', async () => {
            const insightResource: TerraformExportResource = {
                type: 'insight',
                data: {
                    id: 123,
                    name: 'My Test Insight',
                },
            }

            jest.spyOn(insightHclExporter, 'generateInsightHCL').mockImplementation(() => {
                throw new Error('Cannot read property of null')
            })

            const { result } = renderHook(() => useTerraformExport(insightResource, true))

            await waitFor(() => {
                expect(result.current.loading).toBe(false)
            })

            expect(result.current.error).toBe(
                'Failed to generate HCL for insight "My Test Insight" (123): Cannot read property of null'
            )
            expect(result.current.result).toBeNull()
        })

        it('catches generateDashboardHCL errors and provides descriptive message', async () => {
            const dashboardResource: TerraformExportResource = {
                type: 'dashboard',
                data: {
                    id: 456,
                    name: 'My Test Dashboard',
                    tiles: [],
                } as any,
            }

            jest.spyOn(dashboardHclExporter, 'generateDashboardHCL').mockImplementation(() => {
                throw new Error('Unexpected null value')
            })

            const { result } = renderHook(() => useTerraformExport(dashboardResource, true))

            await waitFor(() => {
                expect(result.current.loading).toBe(false)
            })

            expect(result.current.error).toBe(
                'Failed to generate HCL for dashboard "My Test Dashboard" (456): Unexpected null value'
            )
            expect(result.current.result).toBeNull()
        })

        it('captures errors to PostHog with context', async () => {
            const insightResource: TerraformExportResource = {
                type: 'insight',
                data: {
                    id: 789,
                    name: 'Tracked Insight',
                },
            }

            const testError = new Error('Test error for tracking')
            jest.spyOn(insightHclExporter, 'generateInsightHCL').mockImplementation(() => {
                throw testError
            })

            const { result } = renderHook(() => useTerraformExport(insightResource, true))

            await waitFor(() => {
                expect(result.current.loading).toBe(false)
            })

            expect(posthog.captureException).toHaveBeenCalledWith(
                expect.objectContaining({
                    message: 'Failed to generate HCL for insight "Tracked Insight" (789): Test error for tracking',
                }),
                {
                    extra: {
                        context: 'TerraformExporter',
                        resourceType: 'insight',
                        resourceId: 789,
                    },
                }
            )
        })

        it('handles non-Error exceptions gracefully', async () => {
            const insightResource: TerraformExportResource = {
                type: 'insight',
                data: {
                    id: 999,
                    name: 'Test Insight',
                },
            }

            jest.spyOn(insightHclExporter, 'generateInsightHCL').mockImplementation(() => {
                throw 'String error instead of Error object'
            })

            const { result } = renderHook(() => useTerraformExport(insightResource, true))

            await waitFor(() => {
                expect(result.current.loading).toBe(false)
            })

            expect(result.current.error).toBe(
                'Failed to generate HCL for insight "Test Insight" (999): String error instead of Error object'
            )
        })
    })

    describe('successful export', () => {
        it('returns result on successful insight export', async () => {
            const insightResource: TerraformExportResource = {
                type: 'insight',
                data: {
                    id: 123,
                    name: 'Working Insight',
                },
            }

            const mockResult = {
                hcl: 'resource "posthog_insight" "working_insight" {}',
                warnings: [],
                resourceCounts: { dashboards: 0, insights: 1, alerts: 0, hogFunctions: 0 },
            }

            jest.spyOn(insightHclExporter, 'generateInsightHCL').mockReturnValue(mockResult)

            const { result } = renderHook(() => useTerraformExport(insightResource, true))

            await waitFor(() => {
                expect(result.current.loading).toBe(false)
            })

            expect(result.current.error).toBeNull()
            expect(result.current.result).toEqual(mockResult)
        })
    })

    describe('loading state', () => {
        it('does not fetch when modal is closed', () => {
            const insightResource: TerraformExportResource = {
                type: 'insight',
                data: {
                    id: 123,
                    name: 'Test',
                },
            }

            const generateSpy = jest.spyOn(insightHclExporter, 'generateInsightHCL')

            renderHook(() => useTerraformExport(insightResource, false))

            expect(generateSpy).not.toHaveBeenCalled()
        })
    })
})
