import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'
import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'

import { CodeEnumApi } from '../generated/api.schemas'
import type {
    DatasetExportReadApi,
    DatasetItemReadApi as DatasetItem,
    DatasetReadApi as Dataset,
} from '../generated/api.schemas'
import { DatasetFormValues, DatasetLogicProps, aiObservabilityDatasetLogic } from './aiObservabilityDatasetLogic'
import { aiObservabilityDatasetsLogic } from './aiObservabilityDatasetsLogic'
import { datasetsApi } from './datasetsApi'
import { EMPTY_JSON } from './utils'

jest.mock('./datasetsApi', () => ({
    datasetsApi: {
        createDataset: jest.fn(),
        updateDataset: jest.fn(),
        getDataset: jest.fn(),
        getItem: jest.fn(),
        listDatasets: jest.fn(),
        listItems: jest.fn(),
        listItemVersions: jest.fn(),
        listRevisions: jest.fn(),
        archiveDataset: jest.fn(),
        restoreDataset: jest.fn(),
        updateItem: jest.fn(),
        archiveItem: jest.fn(),
        restoreItem: jest.fn(),
        exportDataset: jest.fn(),
        getExport: jest.fn(),
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
        user_access_level: 'editor',
    }

    const mockDatasetItem1: DatasetItem = {
        id: 'item-1',
        dataset: 'test-dataset-id',
        client_item_id: null,
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
        client_item_id: null,
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
    const mockDatasetExport: DatasetExportReadApi = {
        id: 123,
        status: 'pending' as const,
        dataset_revision: 7,
        filename: 'test-dataset.jsonl',
        created_at: '2024-01-01T00:00:00Z',
        expires_after: '2024-01-08T00:00:00Z',
        exception: null,
    }

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
        mockDatasetsApi.getItem.mockImplementation(async (itemId) => {
            const item = [mockDatasetItem1, mockDatasetItem2].find(({ id }) => id === itemId)
            if (!item) {
                throw new ApiError('Not found', 404)
            }
            return item
        })
        mockDatasetsApi.listItemVersions.mockResolvedValue({ results: [], count: 0 })
        mockDatasetsApi.listRevisions.mockResolvedValue({ results: [], count: 0 })
        mockDatasetsApi.updateItem.mockResolvedValue(mockDatasetItem1)
        mockDatasetsApi.exportDataset.mockResolvedValue(mockDatasetExport)
        mockDatasetsApi.getExport.mockResolvedValue({
            ...mockDatasetExport,
            status: 'complete',
        })
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

    describe('dataset export', () => {
        it('starts an export and links to the exports list without staying loading', async () => {
            const logic = aiObservabilityDatasetLogic({ datasetId: mockDataset.id })
            logic.mount()
            const trackExportSpy = jest.spyOn(logic.actions, 'trackExport')

            await expectLogic(logic, () => logic.actions.exportDataset(7)).toFinishAllListeners()

            expect(trackExportSpy).toHaveBeenCalledWith(
                expect.objectContaining({
                    id: mockDatasetExport.id,
                    export_format: 'application/x-ndjson',
                    has_content: false,
                }),
                expect.any(Function)
            )

            const setAssetFormat = jest.fn()
            const findExportsLogicSpy = jest
                .spyOn(exportsLogic, 'findMounted')
                .mockReturnValue({ actions: { setAssetFormat } } as any)

            expect(mockDatasetsApi.exportDataset).toHaveBeenCalledWith(mockDataset.id, 7)
            expect(logic.values.datasetExport).toEqual(mockDatasetExport)
            expect(logic.values.datasetExportLoading).toBe(false)
            expect(lemonToast.info).toHaveBeenCalledWith(
                `Dataset revision ${mockDatasetExport.dataset_revision} was added to exports.`,
                {
                    button: {
                        label: 'View exports',
                        action: expect.any(Function),
                    },
                }
            )
            const toastOptions = (lemonToast.info as jest.Mock).mock.calls.at(-1)?.[1] as {
                button: { action: () => void }
            }
            toastOptions.button.action()

            expect(setAssetFormat).toHaveBeenCalledWith(null)
            expect(router.values.location.pathname).toContain(urls.exports())
            findExportsLogicSpy.mockRestore()
        })

        it('reports a workflow start failure without tracking it as pending', async () => {
            mockDatasetsApi.exportDataset.mockResolvedValue({
                ...mockDatasetExport,
                status: 'failed',
                exception: 'The export could not be started.',
            })
            const logic = aiObservabilityDatasetLogic({ datasetId: mockDataset.id })
            logic.mount()
            const trackExportSpy = jest.spyOn(logic.actions, 'trackExport')

            await expectLogic(logic, () => logic.actions.exportDataset(7)).toFinishAllListeners()

            expect(trackExportSpy).not.toHaveBeenCalled()
            expect(lemonToast.error).toHaveBeenCalledWith('The export could not be started.')
            expect(lemonToast.info).not.toHaveBeenCalled()
        })

        it('retries export creation when a new request fails after an earlier export succeeded', async () => {
            const logic = aiObservabilityDatasetLogic({ datasetId: mockDataset.id })
            logic.mount()
            logic.actions.exportDatasetSuccess(mockDatasetExport)
            mockDatasetsApi.exportDataset.mockRejectedValue(new ApiError('Export failed', 500))
            silenceKeaLoadersErrors()

            try {
                await expectLogic(logic, () => logic.actions.exportDataset(8)).toFinishAllListeners()
            } finally {
                resumeKeaLoadersErrors()
            }

            expect(logic.values.datasetExport).toEqual(mockDatasetExport)
            expect(logic.values.datasetExportLoadError?.status).toBe(500)
            expect(logic.values.datasetExportLoading).toBe(false)
        })
    })

    describe('dataset revisions', () => {
        it('stores revision loading errors and clears them on retry', async () => {
            const logic = aiObservabilityDatasetLogic({ datasetId: mockDataset.id })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            mockDatasetsApi.listRevisions.mockRejectedValue(new ApiError('Revision load failed', 500))
            silenceKeaLoadersErrors()

            try {
                await expectLogic(logic, () => logic.actions.loadDatasetRevisions()).toDispatchActions([
                    'loadDatasetRevisionsFailure',
                ])

                expect(logic.values.datasetRevisionsLoadError).toBeInstanceOf(ApiError)
                expect(logic.values.datasetRevisionsLoadError?.message).toBe('Revision load failed')

                mockDatasetsApi.listRevisions.mockResolvedValue({ results: [], count: 0 })
                await expectLogic(logic, () => logic.actions.loadDatasetRevisions()).toFinishAllListeners()

                expect(logic.values.datasetRevisionsLoadError).toBeNull()
            } finally {
                resumeKeaLoadersErrors()
            }
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

        it('reloads the open item when unarchiving an outdated version', async () => {
            const archivedItem = { ...mockDatasetItem1, archived: true, version: 2 }
            const reloadedItem = { ...archivedItem, version: 3 }
            const errorDetail = 'This dataset item changed after it was loaded. Reload it and try again.'
            mockDatasetsApi.getItem.mockResolvedValue(archivedItem)
            const logic = aiObservabilityDatasetLogic({ datasetId: mockDataset.id })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            await expectLogic(logic, () => {
                router.actions.push(urls.aiObservabilityDataset(mockDataset.id), { item: archivedItem.id })
            }).toFinishAllListeners()
            mockDatasetsApi.restoreItem.mockRejectedValue(
                new ApiError(errorDetail, 409, undefined, {
                    code: CodeEnumApi.StaleVersion,
                    detail: errorDetail,
                    current_version: reloadedItem.version,
                })
            )

            await expectLogic(logic, () => {
                logic.actions.restoreDatasetItem(archivedItem.id, archivedItem.version)
            }).toFinishAllListeners()

            mockDatasetsApi.getItem.mockResolvedValue(reloadedItem)
            const toastOptions = (lemonToast.error as jest.Mock).mock.calls.at(-1)?.[1] as {
                button: { action: () => void }
            }
            toastOptions.button.action()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.selectedDatasetItem).toEqual(reloadedItem)
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
        const props: DatasetLogicProps = { datasetId: mockDataset.id }

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
                    archived: false,
                    revision: null,
                })
            })

            it('cleans and validates filter parameters', () => {
                logic.actions.setFilters({ page: '3' as any, limit: '25' as any })
                expect(logic.values.filters).toEqual({
                    page: 3,
                    limit: 25,
                    archived: false,
                    revision: null,
                })
            })

            it('handles invalid page parameter by setting default', () => {
                logic.actions.setFilters({ page: 'invalid' as any, limit: 25 })
                expect(logic.values.filters).toEqual({
                    page: 1,
                    limit: 25,
                    archived: false,
                    revision: null,
                })
            })

            it('handles invalid limit parameter by setting default', () => {
                logic.actions.setFilters({ page: 2, limit: 'invalid' as any })
                expect(logic.values.filters).toEqual({
                    page: 2,
                    limit: 25,
                    archived: false,
                    revision: null,
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
                    dataset: mockDataset.id,
                    offset: 25,
                    limit: 25,
                    archived: false,
                    revision: undefined,
                })
            })

            it('calculates correct offset for pagination', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setFilters({ page: 3, limit: 25 })
                }).toFinishAllListeners()

                expect(mockDatasetsApi.listItems).toHaveBeenCalledWith({
                    dataset: mockDataset.id,
                    offset: 50,
                    limit: 25,
                    archived: false,
                    revision: undefined,
                })
            })

            it('does not trigger API call when filters do not change', async () => {
                const initialCallCount = mockDatasetsApi.listItems.mock.calls.length

                await expectLogic(logic, () => {
                    logic.actions.setFilters({ page: 1, limit: 25 })
                }).toFinishAllListeners()

                expect(mockDatasetsApi.listItems).toHaveBeenCalledTimes(initialCallCount) // Should not increase
            })

            it('clears old rows and keeps the load error when a filter request fails', async () => {
                await expectLogic(logic).toFinishAllListeners()
                logic.actions.loadDatasetItemsSuccess({ results: [mockDatasetItem1], count: 1 })
                mockDatasetsApi.listItems.mockRejectedValue(new ApiError('Could not load items', 500))
                silenceKeaLoadersErrors()

                try {
                    await expectLogic(logic, () => {
                        logic.actions.setFilters({ revision: 7 }, false)
                    }).toFinishAllListeners()
                } finally {
                    resumeKeaLoadersErrors()
                }

                expect(logic.values.datasetItems).toEqual({ results: [], count: 0 })
                expect(logic.values.datasetItemsLoadError?.status).toBe(500)
            })
        })

        describe('dataset item modal and URL state', () => {
            it('opens modal when dataset item details load', () => {
                const mockDatasetItems = {
                    results: [mockDatasetItem1, mockDatasetItem2],
                    count: 2,
                    offset: 0,
                }

                logic.actions.loadDatasetItemsSuccess(mockDatasetItems)
                logic.actions.loadDatasetItemDetailsSuccess(mockDatasetItem1, { itemId: mockDatasetItem1.id })

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
                logic.actions.loadDatasetItemDetailsSuccess(mockDatasetItem1, { itemId: mockDatasetItem1.id })

                await expectLogic(logic, () => {
                    logic.actions.closeModalAndRefetchDatasetItems(false)
                }).toFinishAllListeners()

                expect(logic.values.selectedDatasetItem).toBe(null)
                expect(logic.values.isDatasetItemModalOpen).toBe(false)
            })

            it('refetches dataset items when requested on modal close', async () => {
                const initialItemCallCount = mockDatasetsApi.listItems.mock.calls.length
                const initialDatasetCallCount = mockDatasetsApi.getDataset.mock.calls.length
                const initialRevisionCallCount = mockDatasetsApi.listRevisions.mock.calls.length

                await expectLogic(logic, () => {
                    logic.actions.closeModalAndRefetchDatasetItems(true)
                }).toFinishAllListeners()

                expect(mockDatasetsApi.listItems).toHaveBeenCalledTimes(initialItemCallCount + 1)
                expect(mockDatasetsApi.getDataset).toHaveBeenCalledTimes(initialDatasetCallCount + 1)
                expect(mockDatasetsApi.listRevisions).toHaveBeenCalledTimes(initialRevisionCallCount + 1)
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
                const datasetUrl = urls.aiObservabilityDataset(mockDataset.id)

                await expectLogic(logic, () => {
                    router.actions.push(datasetUrl, { item: 'item-1', page: '1' })
                }).toFinishAllListeners()

                // Verify modal opens with correct item selected
                expect(mockDatasetsApi.getItem).toHaveBeenCalledWith('item-1', undefined)
                expect(logic.values.selectedDatasetItem).toEqual(mockDatasetItem1)
                expect(logic.values.isDatasetItemModalOpen).toBe(true)
            })

            it('rejects a deep-linked item from another dataset', async () => {
                const datasetUrl = urls.aiObservabilityDataset(mockDataset.id)
                mockDatasetsApi.getItem.mockResolvedValue({ ...mockDatasetItem1, dataset: 'another-dataset' })
                silenceKeaLoadersErrors()

                try {
                    await expectLogic(logic, () => {
                        router.actions.push(datasetUrl, { item: mockDatasetItem1.id })
                    }).toFinishAllListeners()
                } finally {
                    resumeKeaLoadersErrors()
                }

                expect(logic.values.selectedDatasetItem).toBe(null)
                expect(logic.values.selectedDatasetItemLoadError?.status).toBe(404)
            })

            it('ignores an item error after the modal closes', async () => {
                const datasetUrl = urls.aiObservabilityDataset(mockDataset.id)
                let rejectItemRequest: (error: ApiError) => void = () => undefined
                mockDatasetsApi.getItem.mockReturnValueOnce(
                    new Promise((_, reject) => {
                        rejectItemRequest = reject
                    })
                )

                router.actions.push(datasetUrl, { item: mockDatasetItem1.id })
                expect(logic.values.selectedDatasetItemDetailsLoading).toBe(true)

                router.actions.push(datasetUrl)
                logic.actions.triggerDatasetItemModal(true)
                expect(logic.values.selectedDatasetItemDetailsLoading).toBe(false)

                rejectItemRequest(new ApiError('Could not load item', 500))
                await expectLogic(logic).toFinishAllListeners()

                expect(logic.values.selectedDatasetItemLoadError).toBe(null)
                expect(logic.values.isDatasetItemModalOpen).toBe(true)
            })

            it('does not show another item history after a history request fails', async () => {
                const datasetUrl = urls.aiObservabilityDataset(mockDataset.id)
                mockDatasetsApi.listItemVersions.mockResolvedValueOnce({
                    results: [mockDatasetItem1],
                    count: 1,
                })

                await expectLogic(logic, () => {
                    router.actions.push(datasetUrl, { item: mockDatasetItem1.id })
                }).toFinishAllListeners()

                expect(logic.values.selectedDatasetItemVersions.results).toEqual([mockDatasetItem1])

                mockDatasetsApi.listItemVersions.mockRejectedValueOnce(new ApiError('Could not load history', 500))
                silenceKeaLoadersErrors()
                try {
                    await expectLogic(logic, () => {
                        router.actions.push(datasetUrl, { item: mockDatasetItem2.id })
                    }).toFinishAllListeners()
                } finally {
                    resumeKeaLoadersErrors()
                }

                expect(logic.values.selectedDatasetItem).toEqual(mockDatasetItem2)
                expect(logic.values.selectedDatasetItemVersions).toEqual({ results: [], count: 0 })
                expect(logic.values.datasetItemVersionsLoadError?.status).toBe(500)
            })

            it('paginates item history 25 versions at a time', async () => {
                const datasetUrl = urls.aiObservabilityDataset(mockDataset.id)

                await expectLogic(logic, () => {
                    router.actions.push(datasetUrl, { item: mockDatasetItem1.id })
                }).toFinishAllListeners()

                expect(mockDatasetsApi.listItemVersions).toHaveBeenLastCalledWith(mockDatasetItem1.id, {
                    limit: 25,
                    offset: 0,
                })

                await expectLogic(logic, () => {
                    logic.actions.loadDatasetItemVersions({ itemId: mockDatasetItem1.id, page: 2 })
                }).toFinishAllListeners()

                expect(mockDatasetsApi.listItemVersions).toHaveBeenLastCalledWith(mockDatasetItem1.id, {
                    limit: 25,
                    offset: 25,
                })
            })

            it('reloads item history once after a stale version restore', async () => {
                const datasetUrl = urls.aiObservabilityDataset(mockDataset.id)
                const currentItem = { ...mockDatasetItem1, version: 3 }
                const historicalItem = { ...mockDatasetItem1, version: 2 }
                const reloadedItem = { ...mockDatasetItem1, version: 4 }
                const errorDetail = 'This dataset item changed after it was loaded. Reload it and try again.'
                mockDatasetsApi.getItem.mockResolvedValue(currentItem)
                mockDatasetsApi.listItemVersions.mockResolvedValue({ results: [historicalItem], count: 1 })

                await expectLogic(logic, () => {
                    router.actions.push(datasetUrl, { item: currentItem.id })
                }).toFinishAllListeners()

                mockDatasetsApi.listItemVersions.mockClear()
                mockDatasetsApi.updateItem.mockRejectedValue(
                    new ApiError(errorDetail, 409, undefined, {
                        code: CodeEnumApi.StaleVersion,
                        detail: errorDetail,
                        current_version: reloadedItem.version,
                    })
                )
                await expectLogic(logic, () => {
                    logic.actions.restoreDatasetItemVersion(historicalItem.version)
                }).toFinishAllListeners()

                mockDatasetsApi.getItem.mockResolvedValue(reloadedItem)
                const toastOptions = (lemonToast.error as jest.Mock).mock.calls.at(-1)?.[1] as {
                    button: { action: () => void }
                }
                toastOptions.button.action()
                await expectLogic(logic).toFinishAllListeners()

                expect(logic.values.selectedDatasetItem).toEqual(reloadedItem)
                expect(mockDatasetsApi.listItemVersions).toHaveBeenCalledTimes(1)
            })

            it('does not restore a history row that belongs to another item', async () => {
                const datasetUrl = urls.aiObservabilityDataset(mockDataset.id)

                await expectLogic(logic, () => {
                    router.actions.push(datasetUrl, { item: mockDatasetItem2.id })
                }).toFinishAllListeners()

                logic.actions.loadDatasetItemVersionsSuccess(
                    { results: [{ ...mockDatasetItem1, version: 2 }], count: 1 },
                    { itemId: mockDatasetItem2.id, page: 1 }
                )

                await expectLogic(logic, () => {
                    logic.actions.restoreDatasetItemVersion(2)
                }).toFinishAllListeners()

                expect(mockDatasetsApi.updateItem).not.toHaveBeenCalled()
                expect(lemonToast.error).toHaveBeenCalledWith(
                    "Couldn't find that item version. Reload the history and try again."
                )
            })

            it('clears a deep-linked item error when the item is removed from the URL', async () => {
                const datasetUrl = urls.aiObservabilityDataset(mockDataset.id)
                silenceKeaLoadersErrors()

                try {
                    await expectLogic(logic, () => {
                        router.actions.push(datasetUrl, { item: 'non-existent-item', page: '1' })
                    }).toFinishAllListeners()
                } finally {
                    resumeKeaLoadersErrors()
                }

                expect(logic.values.selectedDatasetItem).toBe(null)
                expect(logic.values.isDatasetItemModalOpen).toBe(true)
                expect(logic.values.selectedDatasetItemLoadError?.status).toBe(404)

                await expectLogic(logic, () => {
                    router.actions.push(datasetUrl, { page: '1' })
                }).toFinishAllListeners()

                expect(logic.values.isDatasetItemModalOpen).toBe(false)
                expect(logic.values.selectedDatasetItemLoadError).toBe(null)
            })

            it('sets filters from URL parameters via urlToAction', async () => {
                const datasetUrl = urls.aiObservabilityDataset(mockDataset.id)

                await expectLogic(logic, () => {
                    router.actions.push(datasetUrl, { page: '3', limit: '25' })
                }).toFinishAllListeners()

                // Verify filters are set from URL
                expect(logic.values.filters).toEqual({
                    page: 3,
                    limit: 25,
                    archived: false,
                    revision: null,
                })
            })

            it('loads an exact revision and archived items from URL state', async () => {
                const datasetUrl = urls.aiObservabilityDataset(mockDataset.id)

                await expectLogic(logic, () => {
                    router.actions.push(datasetUrl, {
                        item: 'item-1',
                        item_status: 'archived',
                        revision: '12',
                    })
                }).toFinishAllListeners()

                expect(logic.values.filters).toMatchObject({ archived: true, revision: 12 })
                expect(mockDatasetsApi.getItem).toHaveBeenCalledWith('item-1', 12)
                expect(mockDatasetsApi.listItems).toHaveBeenLastCalledWith({
                    dataset: mockDataset.id,
                    offset: 0,
                    limit: 25,
                    archived: true,
                    revision: 12,
                })
            })

            it('sets active tab from URL parameters via urlToAction', async () => {
                const datasetUrl = urls.aiObservabilityDataset(mockDataset.id)

                await expectLogic(logic, () => {
                    router.actions.push(datasetUrl, { tab: 'metadata', page: '1' })
                }).toFinishAllListeners()

                // Verify tab is set from URL
                expect(logic.values.activeTab).toBe('metadata')
            })

            it('closes modal and clears state when closeModalAndRefetchDatasetItems is called', async () => {
                logic.actions.loadDatasetItemDetailsSuccess(mockDatasetItem1, { itemId: mockDatasetItem1.id })

                // Close modal
                await expectLogic(logic, () => {
                    logic.actions.closeModalAndRefetchDatasetItems(false)
                }).toFinishAllListeners()

                // Verify modal state is cleared
                expect(logic.values.selectedDatasetItem).toBe(null)
                expect(logic.values.isDatasetItemModalOpen).toBe(false)
            })

            it('handles complete workflow: URL -> modal -> close', async () => {
                const datasetUrl = urls.aiObservabilityDataset(mockDataset.id)

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
