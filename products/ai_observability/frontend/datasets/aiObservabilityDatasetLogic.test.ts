import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { CodeEnumApi } from '../generated/api.schemas'
import type { DatasetItemReadApi as DatasetItem, DatasetReadApi as Dataset } from '../generated/api.schemas'
import { DatasetFormValues, DatasetLogicProps, aiObservabilityDatasetLogic } from './aiObservabilityDatasetLogic'
import { aiObservabilityDatasetsLogic } from './aiObservabilityDatasetsLogic'
import { datasetsApi } from './datasetsApi'
import { EMPTY_JSON } from './utils'

jest.mock('./datasetsApi', () => ({
    datasetsApi: {
        createDataset: jest.fn(),
        updateDataset: jest.fn(),
        getDataset: jest.fn(),
        listDatasets: jest.fn(),
        listItems: jest.fn(),
        archiveDataset: jest.fn(),
        restoreDataset: jest.fn(),
        archiveItem: jest.fn(),
        restoreItem: jest.fn(),
    },
}))
jest.mock('lib/lemon-ui/LemonToast/LemonToast')

describe('aiObservabilityDatasetLogic', () => {
    const mockDataset: Dataset = {
        id: 'test-dataset-id',
        name: 'Test Dataset',
        description: 'Test description',
        metadata: { key: 'value' },
        team_id: 997,
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
        created_by: null,
        archived: false,
        current_revision: null,
        current_revision_id: null,
    }

    const mockDatasetItem1: DatasetItem = {
        id: 'item-1',
        dataset: 'test-dataset-id',
        external_id: null,
        version: 1,
        version_id: 'item-version-1',
        dataset_revision: 1,
        dataset_revision_id: 'dataset-revision-1',
        archived: false,
        input: { query: 'test input' },
        expected_output: { response: 'test response 1' },
        source_output: null,
        metadata: { key: 'value' },
        source_trace_id: null,
        source_timestamp: null,
        source_event_id: null,
        created_by: null,
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
        version_created_at: '2024-01-01T00:00:00Z',
        version_created_by: null,
        team_id: 997,
    }

    const mockDatasetItem2: DatasetItem = {
        id: 'item-2',
        dataset: 'test-dataset-id',
        external_id: null,
        version: 1,
        version_id: 'item-version-2',
        dataset_revision: 2,
        dataset_revision_id: 'dataset-revision-2',
        archived: false,
        input: { query: 'test input 2' },
        expected_output: { response: 'test response 2' },
        source_output: null,
        metadata: { key: 'value2' },
        source_trace_id: null,
        source_timestamp: null,
        source_event_id: null,
        created_by: null,
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
        version_created_at: '2024-01-01T00:00:00Z',
        version_created_by: null,
        team_id: 997,
    }

    const mockDatasetsApi = jest.mocked(datasetsApi)

    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()

        mockDatasetsApi.createDataset.mockResolvedValue(mockDataset)
        mockDatasetsApi.updateDataset.mockResolvedValue(mockDataset)
        // Mounting with an existing datasetId fires loadDataset/loadDatasetItems/loadDatasets;
        // resolving undefined makes each loader reducer log a KEA error. Default to real shapes.
        mockDatasetsApi.getDataset.mockResolvedValue(mockDataset)
        mockDatasetsApi.listDatasets.mockResolvedValue({ results: [], count: 0 })
        mockDatasetsApi.listItems.mockResolvedValue({ results: [], count: 0 })
        mockDatasetsApi.archiveDataset.mockResolvedValue({ ...mockDataset, archived: true })
        mockDatasetsApi.restoreDataset.mockResolvedValue(mockDataset)
        mockDatasetsApi.archiveItem.mockResolvedValue({ ...mockDatasetItem1, archived: true, version: 2 })
        mockDatasetsApi.restoreItem.mockResolvedValue({ ...mockDatasetItem1, version: 3 })
    })

    describe('new dataset creation', () => {
        let logic: ReturnType<typeof aiObservabilityDatasetLogic.build>
        const props: DatasetLogicProps = { datasetId: 'new' }

        beforeEach(() => {
            logic = aiObservabilityDatasetLogic(props)
            logic.mount()
        })

        it('has correct defaults for new dataset', () => {
            expect(logic.values.isNewDataset).toBe(true)
            expect(logic.values.dataset).toEqual({
                name: '',
                description: '',
                metadata: EMPTY_JSON,
            })
            expect(logic.values.datasetForm).toEqual({
                name: '',
                description: '',
                metadata: EMPTY_JSON,
            })
        })

        it('can create a new dataset with non-empty metadata', async () => {
            const formValues: DatasetFormValues = {
                name: 'New Dataset',
                description: 'New description',
                metadata: '{"test": "value"}',
            }

            mockDatasetsApi.createDataset.mockResolvedValue(mockDataset)
            const routerReplaceSpy = jest.spyOn(router.actions, 'replace')

            await expectLogic(logic, () => {
                logic.actions.setDatasetFormValues(formValues)
                logic.actions.submitDatasetForm()
            }).toFinishAllListeners()

            expect(mockDatasetsApi.createDataset).toHaveBeenCalledWith({
                name: 'New Dataset',
                description: 'New description',
                metadata: { test: 'value' },
            })
            expect(lemonToast.success).toHaveBeenCalledWith('Dataset created successfully')
            expect(routerReplaceSpy).toHaveBeenCalledWith(urls.aiObservabilityDataset(mockDataset.id))
            expect(logic.values.dataset).toEqual(mockDataset)
            expect(logic.values.isEditingDataset).toBe(false)
        })

        it('sends an empty object for empty object metadata when creating dataset', async () => {
            const formValues: DatasetFormValues = {
                name: 'New Dataset',
                description: 'New description',
                metadata: EMPTY_JSON,
            }

            await expectLogic(logic, () => {
                logic.actions.setDatasetFormValues(formValues)
                logic.actions.submitDatasetForm()
            }).toFinishAllListeners()

            expect(mockDatasetsApi.createDataset).toHaveBeenCalledWith({
                name: 'New Dataset',
                description: 'New description',
                metadata: {},
            })
        })

        it('sends an empty object for empty string metadata when creating dataset', async () => {
            const formValues: DatasetFormValues = {
                name: 'New Dataset',
                description: 'New description',
                metadata: '',
            }

            await expectLogic(logic, () => {
                logic.actions.setDatasetFormValues(formValues)
                logic.actions.submitDatasetForm()
            }).toFinishAllListeners()

            expect(mockDatasetsApi.createDataset).toHaveBeenCalledWith({
                name: 'New Dataset',
                description: 'New description',
                metadata: {},
            })
        })

        it('sends dictionary for non-empty metadata when creating dataset', async () => {
            const formValues: DatasetFormValues = {
                name: 'New Dataset',
                description: 'New description',
                metadata: '{"nested": {"key": "value"}, "array": [1, 2, 3]}',
            }

            await expectLogic(logic, () => {
                logic.actions.setDatasetFormValues(formValues)
                logic.actions.submitDatasetForm()
            }).toFinishAllListeners()

            expect(mockDatasetsApi.createDataset).toHaveBeenCalledWith({
                name: 'New Dataset',
                description: 'New description',
                metadata: { nested: { key: 'value' }, array: [1, 2, 3] },
            })
        })

        it('handles creation error', async () => {
            const formValues: DatasetFormValues = {
                name: 'New Dataset',
                description: 'New description',
                metadata: '{"test": "value"}',
            }

            const error = { detail: 'Custom error message' }
            mockDatasetsApi.createDataset.mockRejectedValue(error)

            await expectLogic(logic, () => {
                logic.actions.setDatasetFormValues(formValues)
                logic.actions.submitDatasetForm()
            }).toFinishAllListeners()

            expect(lemonToast.error).toHaveBeenCalledWith('Custom error message')
        })

        it('handles creation error without detail', async () => {
            const formValues: DatasetFormValues = {
                name: 'New Dataset',
                description: 'New description',
                metadata: '{"test": "value"}',
            }

            const error = new Error('Network error')
            mockDatasetsApi.createDataset.mockRejectedValue(error)

            await expectLogic(logic, () => {
                logic.actions.setDatasetFormValues(formValues)
                logic.actions.submitDatasetForm()
            }).toFinishAllListeners()

            expect(lemonToast.error).toHaveBeenCalledWith('Failed to save dataset')
        })
    })

    describe('existing dataset editing', () => {
        let logic: ReturnType<typeof aiObservabilityDatasetLogic.build>
        const props: DatasetLogicProps = { datasetId: 'existing-dataset-id' }

        beforeEach(() => {
            logic = aiObservabilityDatasetLogic(props)
            logic.mount()
        })

        it('has correct defaults for existing dataset', () => {
            expect(logic.values.isNewDataset).toBe(false)
        })

        it('can edit an existing dataset', async () => {
            const formValues: DatasetFormValues = {
                name: 'Updated Dataset',
                description: 'Updated description',
                metadata: '{"updated": "metadata"}',
            }

            const updatedDataset: Dataset = {
                ...mockDataset,
                name: formValues.name,
                description: formValues.description,
                metadata: { updated: 'metadata' },
            }
            mockDatasetsApi.updateDataset.mockResolvedValue(updatedDataset)

            await expectLogic(logic, () => {
                logic.actions.setDatasetFormValues(formValues)
                logic.actions.submitDatasetForm()
            }).toFinishAllListeners()

            expect(mockDatasetsApi.updateDataset).toHaveBeenCalledWith('existing-dataset-id', {
                name: 'Updated Dataset',
                description: 'Updated description',
                metadata: { updated: 'metadata' },
            })
            expect(lemonToast.success).toHaveBeenCalledWith('Dataset updated successfully')
            expect(logic.values.dataset).toEqual(updatedDataset)
            expect(logic.values.isEditingDataset).toBe(false)
        })

        it('sends an empty object for empty object metadata when editing dataset', async () => {
            const formValues: DatasetFormValues = {
                name: 'Updated Dataset',
                description: 'Updated description',
                metadata: EMPTY_JSON,
            }

            await expectLogic(logic, () => {
                logic.actions.setDatasetFormValues(formValues)
                logic.actions.submitDatasetForm()
            }).toFinishAllListeners()

            expect(mockDatasetsApi.updateDataset).toHaveBeenCalledWith('existing-dataset-id', {
                name: 'Updated Dataset',
                description: 'Updated description',
                metadata: {},
            })
        })

        it('handles update error', async () => {
            const formValues: DatasetFormValues = {
                name: 'Updated Dataset',
                description: 'Updated description',
                metadata: '{"test": "value"}',
            }

            const error = { detail: 'Update failed' }
            mockDatasetsApi.updateDataset.mockRejectedValue(error)

            await expectLogic(logic, () => {
                logic.actions.setDatasetFormValues(formValues)
                logic.actions.submitDatasetForm()
            }).toFinishAllListeners()

            expect(lemonToast.error).toHaveBeenCalledWith('Update failed')
        })
    })

    describe('dataset archiving', () => {
        let logic: ReturnType<typeof aiObservabilityDatasetLogic.build>

        beforeEach(async () => {
            logic = aiObservabilityDatasetLogic({ datasetId: mockDataset.id })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
        })

        it('restores the dataset and reloads the active list from Undo', async () => {
            const datasetsLogic = aiObservabilityDatasetsLogic()
            datasetsLogic.mount()
            await expectLogic(datasetsLogic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.archiveDataset()
            }).toFinishAllListeners()
            await expectLogic(datasetsLogic).toFinishAllListeners()

            const listCallCount = mockDatasetsApi.listDatasets.mock.calls.length
            const toastOptions = (lemonToast.info as jest.Mock).mock.calls.at(-1)?.[1] as {
                button: { action: () => Promise<void> }
            }

            await toastOptions.button.action()
            await expectLogic(datasetsLogic).toFinishAllListeners()

            expect(mockDatasetsApi.restoreDataset).toHaveBeenCalledWith(mockDataset.id)
            expect(mockDatasetsApi.listDatasets).toHaveBeenCalledTimes(listCallCount + 1)
            expect(lemonToast.success).toHaveBeenCalledWith('Test Dataset has been restored.')
        })

        it('shows an error when Undo cannot restore the dataset', async () => {
            mockDatasetsApi.restoreDataset.mockRejectedValue(new Error('Network error'))

            await expectLogic(logic, () => {
                logic.actions.archiveDataset()
            }).toFinishAllListeners()

            const toastOptions = (lemonToast.info as jest.Mock).mock.calls.at(-1)?.[1] as {
                button: { action: () => Promise<void> }
            }
            await toastOptions.button.action()

            expect(lemonToast.error).toHaveBeenCalledWith("Couldn't restore dataset. Try again.")
        })
    })

    describe('dataset item archiving', () => {
        it('offers to reload items when archiving an outdated version', async () => {
            const errorDetail = 'This dataset item changed after it was loaded. Reload it and try again.'
            mockDatasetsApi.archiveItem.mockRejectedValue(
                new ApiError(errorDetail, 409, undefined, {
                    code: CodeEnumApi.StaleVersion,
                    detail: errorDetail,
                    current_version: 2,
                })
            )
            const logic = aiObservabilityDatasetLogic({ datasetId: mockDataset.id })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            const listCallCount = mockDatasetsApi.listItems.mock.calls.length

            await expectLogic(logic, () => {
                logic.actions.archiveDatasetItem(mockDatasetItem1.id, mockDatasetItem1.version)
            }).toFinishAllListeners()

            expect(lemonToast.error).toHaveBeenCalledWith(errorDetail, {
                button: {
                    label: 'Reload items',
                    action: expect.any(Function),
                },
            })
            const toastOptions = (lemonToast.error as jest.Mock).mock.calls.at(-1)?.[1] as {
                button: { action: () => void }
            }
            toastOptions.button.action()
            await expectLogic(logic).toFinishAllListeners()

            expect(mockDatasetsApi.listItems).toHaveBeenCalledTimes(listCallCount + 1)
        })

        it('shows an error when Undo cannot restore the item', async () => {
            const logic = aiObservabilityDatasetLogic({ datasetId: mockDataset.id })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            mockDatasetsApi.restoreItem.mockRejectedValue(new Error('Network error'))

            await expectLogic(logic, () => {
                logic.actions.archiveDatasetItem(mockDatasetItem1.id, mockDatasetItem1.version)
            }).toFinishAllListeners()

            const toastOptions = (lemonToast.info as jest.Mock).mock.calls.at(-1)?.[1] as {
                button: { action: () => Promise<void> }
            }
            await toastOptions.button.action()

            expect(mockDatasetsApi.restoreItem).toHaveBeenCalledWith(mockDatasetItem1.id, { base_version: 2 })
            expect(lemonToast.error).toHaveBeenCalledWith(
                "Couldn't restore dataset item. Refresh the dataset and try again."
            )
        })

        it('offers to reload items when Undo finds a newer version', async () => {
            const errorDetail = 'This dataset item changed after it was loaded. Reload it and try again.'
            mockDatasetsApi.restoreItem.mockRejectedValue(
                new ApiError(errorDetail, 409, undefined, {
                    code: CodeEnumApi.StaleVersion,
                    detail: errorDetail,
                    current_version: 3,
                })
            )
            const logic = aiObservabilityDatasetLogic({ datasetId: mockDataset.id })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.archiveDatasetItem(mockDatasetItem1.id, mockDatasetItem1.version)
            }).toFinishAllListeners()

            const undoToastOptions = (lemonToast.info as jest.Mock).mock.calls.at(-1)?.[1] as {
                button: { action: () => Promise<void> }
            }
            await undoToastOptions.button.action()
            const listCallCount = mockDatasetsApi.listItems.mock.calls.length

            expect(lemonToast.error).toHaveBeenCalledWith(errorDetail, {
                button: {
                    label: 'Reload items',
                    action: expect.any(Function),
                },
            })
            const errorToastOptions = (lemonToast.error as jest.Mock).mock.calls.at(-1)?.[1] as {
                button: { action: () => void }
            }
            errorToastOptions.button.action()
            await expectLogic(logic).toFinishAllListeners()

            expect(mockDatasetsApi.listItems).toHaveBeenCalledTimes(listCallCount + 1)
        })
    })

    describe('dataset loading and defaults', () => {
        let logic: ReturnType<typeof aiObservabilityDatasetLogic.build>
        const props: DatasetLogicProps = { datasetId: 'existing-dataset-id' }

        beforeEach(() => {
            logic = aiObservabilityDatasetLogic(props)
        })

        it('loads dataset on mount', async () => {
            mockDatasetsApi.getDataset.mockResolvedValue(mockDataset)
            logic.mount()

            await expectLogic(logic).toFinishAllListeners()

            expect(mockDatasetsApi.getDataset).toHaveBeenCalledWith('existing-dataset-id')
        })

        it('sets form defaults when dataset is loaded', async () => {
            const datasetWithComplexMetadata: Dataset = {
                ...mockDataset,
                metadata: { complex: { nested: 'data' }, array: [1, 2, 3] },
            }

            mockDatasetsApi.getDataset.mockResolvedValue(datasetWithComplexMetadata)
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.loadDatasetSuccess(datasetWithComplexMetadata)
            }).toFinishAllListeners()

            expect(logic.values.datasetForm).toEqual({
                name: 'Test Dataset',
                description: 'Test description',
                metadata: '{\n  "complex": {\n    "nested": "data"\n  },\n  "array": [\n    1,\n    2,\n    3\n  ]\n}',
            })
        })

        it('uses existing dataset from datasets logic if available', () => {
            const datasetsLogic = aiObservabilityDatasetsLogic()
            datasetsLogic.mount()

            // Mock the findMounted method to return the datasets logic
            const findMountedSpy = jest.spyOn(aiObservabilityDatasetsLogic, 'findMounted')
            findMountedSpy.mockReturnValue({
                values: {
                    datasets: {
                        results: [mockDataset],
                    },
                },
            } as any)

            logic = aiObservabilityDatasetLogic({ datasetId: mockDataset.id })
            logic.mount()

            expect(logic.values.dataset).toEqual(mockDataset)
            expect(logic.values.datasetForm).toEqual({
                name: 'Test Dataset',
                description: 'Test description',
                metadata: '{\n  "key": "value"\n}',
            })

            findMountedSpy.mockRestore()
        })

        it('handles empty object metadata correctly in form defaults', () => {
            const datasetWithEmptyMetadata = { ...mockDataset, metadata: {} }

            const findMountedSpy = jest.spyOn(aiObservabilityDatasetsLogic, 'findMounted')
            findMountedSpy.mockReturnValue({
                values: {
                    datasets: {
                        results: [datasetWithEmptyMetadata],
                    },
                },
            } as any)

            logic = aiObservabilityDatasetLogic({ datasetId: datasetWithEmptyMetadata.id })
            logic.mount()

            expect(logic.values.datasetForm.metadata).toBe(EMPTY_JSON)

            findMountedSpy.mockRestore()
        })
    })

    describe('filter functionality', () => {
        let logic: ReturnType<typeof aiObservabilityDatasetLogic.build>
        const props: DatasetLogicProps = { datasetId: 'existing-dataset-id' }

        beforeEach(() => {
            mockDatasetsApi.getDataset.mockResolvedValue(mockDataset)
            mockDatasetsApi.listItems.mockResolvedValue({
                results: [],
                count: 0,
            })
            logic = aiObservabilityDatasetLogic(props)
            logic.mount()
        })

        describe('filter processing and defaults', () => {
            it('applies default filters when no filters set', () => {
                expect(logic.values.filters).toEqual({
                    page: 1,
                    limit: 25,
                })
            })

            it('cleans and validates filter parameters', () => {
                logic.actions.setFilters({ page: '3' as any, limit: '25' as any })
                expect(logic.values.filters).toEqual({
                    page: 3,
                    limit: 25,
                })
            })

            it('handles invalid page parameter by setting default', () => {
                logic.actions.setFilters({ page: 'invalid' as any, limit: 25 })
                expect(logic.values.filters).toEqual({
                    page: 1,
                    limit: 25,
                })
            })

            it('handles invalid limit parameter by setting default', () => {
                logic.actions.setFilters({ page: 2, limit: 'invalid' as any })
                expect(logic.values.filters).toEqual({
                    page: 2,
                    limit: 25,
                })
            })

            it('resets page when other filters change', () => {
                logic.actions.setFilters({ page: 3, limit: 25 })
                expect(logic.values.filters.page).toBe(3)

                // Change limit, should reset page to 1
                logic.actions.setFilters({ limit: 100 })
                expect(logic.values.filters.page).toBe(1)
                expect(logic.values.filters.limit).toBe(100)
            })

            it('preserves page when explicitly changing page', () => {
                logic.actions.setFilters({ page: 2, limit: 25 })
                expect(logic.values.filters.page).toBe(2)

                // Explicitly change page, should not reset
                logic.actions.setFilters({ page: 5 })
                expect(logic.values.filters.page).toBe(5)
            })
        })

        describe('filter-triggered API calls', () => {
            it('loads dataset items when filters change', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setFilters({ page: 2, limit: 25 })
                }).toFinishAllListeners()

                expect(mockDatasetsApi.listItems).toHaveBeenCalledWith({
                    dataset: 'existing-dataset-id',
                    offset: 25,
                    limit: 25,
                })
            })

            it('calculates correct offset for pagination', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setFilters({ page: 3, limit: 25 })
                }).toFinishAllListeners()

                expect(mockDatasetsApi.listItems).toHaveBeenCalledWith({
                    dataset: 'existing-dataset-id',
                    offset: 50,
                    limit: 25,
                })
            })

            it('does not trigger API call when filters do not change', async () => {
                const initialCallCount = mockDatasetsApi.listItems.mock.calls.length

                await expectLogic(logic, () => {
                    logic.actions.setFilters({ page: 1, limit: 25 })
                }).toFinishAllListeners()

                expect(mockDatasetsApi.listItems).toHaveBeenCalledTimes(initialCallCount) // Should not increase
            })
        })

        describe('dataset item modal and URL state', () => {
            it('opens modal when dataset item is selected from data', () => {
                const mockDatasetItems = {
                    results: [mockDatasetItem1, mockDatasetItem2],
                    count: 2,
                    offset: 0,
                }

                logic.actions.loadDatasetItemsSuccess(mockDatasetItems)
                logic.actions.setSelectedDatasetItem(mockDatasetItem1)
                logic.actions.triggerDatasetItemModal(true)

                expect(logic.values.selectedDatasetItem).toEqual(mockDatasetItem1)
                expect(logic.values.isDatasetItemModalOpen).toBe(true)
            })

            it('closes modal and clears selected item', async () => {
                const mockDatasetItems = {
                    results: [mockDatasetItem1],
                    count: 1,
                    offset: 0,
                }

                logic.actions.loadDatasetItemsSuccess(mockDatasetItems)
                logic.actions.setSelectedDatasetItem(mockDatasetItem1)
                logic.actions.triggerDatasetItemModal(true)

                await expectLogic(logic, () => {
                    logic.actions.closeModalAndRefetchDatasetItems(false)
                }).toFinishAllListeners()

                expect(logic.values.selectedDatasetItem).toBe(null)
                expect(logic.values.isDatasetItemModalOpen).toBe(false)
            })

            it('refetches dataset items when requested on modal close', async () => {
                const initialCallCount = mockDatasetsApi.listItems.mock.calls.length

                await expectLogic(logic, () => {
                    logic.actions.closeModalAndRefetchDatasetItems(true)
                }).toFinishAllListeners()

                expect(mockDatasetsApi.listItems).toHaveBeenCalledTimes(initialCallCount + 1)
            })
        })

        describe('URL integration with router', () => {
            beforeEach(() => {
                const mockDatasetItems = {
                    results: [mockDatasetItem1, mockDatasetItem2],
                    count: 2,
                    offset: 0,
                }
                logic.actions.loadDatasetItemsSuccess(mockDatasetItems)
            })

            it('handles URL with item parameter via urlToAction', async () => {
                // Test that urlToAction responds to URL changes with item parameter
                const datasetUrl = urls.aiObservabilityDataset('existing-dataset-id')

                await expectLogic(logic, () => {
                    router.actions.push(datasetUrl, { item: 'item-1', page: '1' })
                }).toFinishAllListeners()

                // Verify modal opens with correct item selected
                expect(logic.values.selectedDatasetItem).toEqual(mockDatasetItem1)
                expect(logic.values.isDatasetItemModalOpen).toBe(true)
            })

            it('ignores URL item parameter when item not found', async () => {
                const datasetUrl = urls.aiObservabilityDataset('existing-dataset-id')

                await expectLogic(logic, () => {
                    router.actions.push(datasetUrl, { item: 'non-existent-item', page: '1' })
                }).toFinishAllListeners()

                // Verify modal stays closed when item not found
                expect(logic.values.selectedDatasetItem).toBe(null)
                expect(logic.values.isDatasetItemModalOpen).toBe(false)
            })

            it('sets filters from URL parameters via urlToAction', async () => {
                const datasetUrl = urls.aiObservabilityDataset('existing-dataset-id')

                await expectLogic(logic, () => {
                    router.actions.push(datasetUrl, { page: '3', limit: '25' })
                }).toFinishAllListeners()

                // Verify filters are set from URL
                expect(logic.values.filters).toEqual({
                    page: 3,
                    limit: 25,
                })
            })

            it('sets active tab from URL parameters via urlToAction', async () => {
                const datasetUrl = urls.aiObservabilityDataset('existing-dataset-id')

                await expectLogic(logic, () => {
                    router.actions.push(datasetUrl, { tab: 'metadata', page: '1' })
                }).toFinishAllListeners()

                // Verify tab is set from URL
                expect(logic.values.activeTab).toBe('metadata')
            })

            it('closes modal and clears state when closeModalAndRefetchDatasetItems is called', async () => {
                // Set up initial state with modal open
                logic.actions.setSelectedDatasetItem(mockDatasetItem1)
                logic.actions.triggerDatasetItemModal(true)

                // Close modal
                await expectLogic(logic, () => {
                    logic.actions.closeModalAndRefetchDatasetItems(false)
                }).toFinishAllListeners()

                // Verify modal state is cleared
                expect(logic.values.selectedDatasetItem).toBe(null)
                expect(logic.values.isDatasetItemModalOpen).toBe(false)
            })

            it('handles complete workflow: URL -> modal -> close', async () => {
                const datasetUrl = urls.aiObservabilityDataset('existing-dataset-id')

                // Step 1: Navigate to URL with item parameter
                await expectLogic(logic, () => {
                    router.actions.push(datasetUrl, { item: 'item-1', page: '1' })
                }).toFinishAllListeners()

                // Verify modal opened via urlToAction
                expect(logic.values.selectedDatasetItem).toEqual(mockDatasetItem1)
                expect(logic.values.isDatasetItemModalOpen).toBe(true)

                // Step 2: Close modal
                await expectLogic(logic, () => {
                    logic.actions.closeModalAndRefetchDatasetItems(false)
                }).toFinishAllListeners()

                // Verify modal state cleared
                expect(logic.values.selectedDatasetItem).toBe(null)
                expect(logic.values.isDatasetItemModalOpen).toBe(false)
            })
        })
    })

    describe('form validation', () => {
        let logic: ReturnType<typeof aiObservabilityDatasetLogic.build>

        beforeEach(() => {
            logic = aiObservabilityDatasetLogic({ datasetId: 'new' })
            logic.mount()
        })

        it('validates required name field', async () => {
            const formValues = { name: '', description: 'test', metadata: '{}' }
            logic.actions.setDatasetFormValues(formValues)

            try {
                await expectLogic(logic, () => {
                    logic.actions.submitDatasetForm()
                }).toFinishAllListeners()
            } catch {
                // Expected to fail validation
            }

            const errors = logic.values.datasetFormErrors
            expect(errors.name).toBe('Dataset name is required')
        })

        it('validates name with only whitespace', async () => {
            const formValues = { name: '   ', description: 'test', metadata: '{}' }
            logic.actions.setDatasetFormValues(formValues)

            try {
                await expectLogic(logic, () => {
                    logic.actions.submitDatasetForm()
                }).toFinishAllListeners()
            } catch {
                // Expected to fail validation
            }

            const errors = logic.values.datasetFormErrors
            expect(errors.name).toBe('Dataset name is required')
        })

        it('validates valid metadata JSON', async () => {
            const formValues = { name: 'test', description: 'test', metadata: '{"valid": "json"}' }
            logic.actions.setDatasetFormValues(formValues)
            logic.actions.touchDatasetFormField('metadata')

            await expectLogic(logic).toFinishAllListeners()

            const errors = logic.values.datasetFormErrors
            expect(errors.metadata).toBeUndefined()
        })

        it('validates invalid metadata JSON', async () => {
            const formValues = { name: 'test', description: 'test', metadata: '{"invalid": json}' }
            logic.actions.setDatasetFormValues(formValues)

            try {
                await expectLogic(logic, () => {
                    logic.actions.submitDatasetForm()
                }).toFinishAllListeners()
            } catch {
                // Expected to fail validation
            }

            const errors = logic.values.datasetFormErrors
            expect(errors.metadata).toBe('Dataset metadata must contain a valid JSON object or be empty')
        })

        it('allows empty metadata', async () => {
            const formValues = { name: 'test', description: 'test', metadata: '' }
            logic.actions.setDatasetFormValues(formValues)
            logic.actions.touchDatasetFormField('metadata')

            await expectLogic(logic).toFinishAllListeners()

            const errors = logic.values.datasetFormErrors
            expect(errors.metadata).toBeUndefined()
        })

        it('allows null metadata', async () => {
            const formValues = { name: 'test', description: 'test', metadata: null }
            logic.actions.setDatasetFormValues(formValues)
            logic.actions.touchDatasetFormField('metadata')

            await expectLogic(logic).toFinishAllListeners()

            const errors = logic.values.datasetFormErrors
            expect(errors.metadata).toBeUndefined()
        })
    })
})
