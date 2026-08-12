import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'

import { CodeEnumApi } from '../generated/api.schemas'
import type { DatasetItemReadApi as DatasetItem } from '../generated/api.schemas'
import { datasetItemModalLogic } from './datasetItemModalLogic'
import { datasetsApi } from './datasetsApi'
import { EMPTY_JSON, isStringJsonValue } from './utils'

jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    lemonToast: {
        error: jest.fn(),
        success: jest.fn(),
    },
}))
jest.mock('./datasetsApi', () => ({
    datasetsApi: {
        createItem: jest.fn(),
        updateItem: jest.fn(),
    },
}))

describe('datasetItemModalLogic', () => {
    const mockDatasetItem: DatasetItem = {
        id: 'test-item-1',
        dataset: 'test-dataset-1',
        client_item_id: null,
        version: 2,
        version_id: 'test-item-version-2',
        dataset_revision: 2,
        dataset_revision_id: 'test-dataset-revision-2',
        archived: false,
        input: { message: 'Hello' },
        expected_output: { response: 'Hi there' },
        source_output: { response: 'Original response' },
        metadata: { source: 'test' },
        source_trace_id: null,
        source_timestamp: null,
        source_event_id: null,
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
        created_by: null,
        version_created_at: '2024-01-02T00:00:00Z',
        version_created_by: null,
        team_id: 997,
    }

    const mockDatasetsApi = jest.mocked(datasetsApi)
    const mockCloseModal = jest.fn()

    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()

        mockDatasetsApi.createItem.mockResolvedValue(mockDatasetItem)
        mockDatasetsApi.updateItem.mockResolvedValue(mockDatasetItem)
    })

    it('save resets shouldCloseModal to true after creating item', async () => {
        const logic = datasetItemModalLogic({
            datasetId: 'test-dataset-1',
            partialDatasetItem: null,
            closeModal: mockCloseModal,
            isModalOpen: true,
        })
        logic.mount()

        // Set shouldCloseModal to false initially
        logic.actions.setShouldCloseModal(false)
        expect(logic.values.shouldCloseModal).toBe(false)

        // Submit form
        await expectLogic(logic, () => {
            logic.actions.submitDatasetItemForm()
        }).toFinishAllListeners()

        expect(logic.values.shouldCloseModal).toBe(true)
    })

    it('save closes modal when shouldCloseModal is true', async () => {
        const logic = datasetItemModalLogic({
            datasetId: 'test-dataset-1',
            partialDatasetItem: null,
            closeModal: mockCloseModal,
            isModalOpen: true,
        })
        logic.mount()

        // shouldCloseModal is true by default
        expect(logic.values.shouldCloseModal).toBe(true)

        // Submit form
        await expectLogic(logic, () => {
            logic.actions.submitDatasetItemForm()
        }).toFinishAllListeners()

        expect(mockCloseModal).toHaveBeenCalledWith(true)
    })

    it('save does not close modal when shouldCloseModal is false', async () => {
        const logic = datasetItemModalLogic({
            datasetId: 'test-dataset-1',
            partialDatasetItem: null,
            closeModal: mockCloseModal,
            isModalOpen: true,
        })
        logic.mount()

        // Set shouldCloseModal to false
        logic.actions.setShouldCloseModal(false)

        // Submit form
        await expectLogic(logic, () => {
            logic.actions.submitDatasetItemForm()
        }).toFinishAllListeners()

        expect(mockCloseModal).not.toHaveBeenCalled()
        expect(logic.values.refetchDatasetItems).toBe(true)
    })

    it('edit closes the modal', async () => {
        const logic = datasetItemModalLogic({
            datasetId: 'test-dataset-1',
            partialDatasetItem: mockDatasetItem,
            closeModal: mockCloseModal,
            isModalOpen: true,
        })
        logic.mount()

        // Mock successful update
        const updatedItem = { ...mockDatasetItem, expected_output: { response: 'Updated response' } }
        mockDatasetsApi.updateItem.mockResolvedValue(updatedItem)

        // Submit form
        await expectLogic(logic, () => {
            logic.actions.submitDatasetItemForm()
        }).toFinishAllListeners()

        expect(mockDatasetsApi.updateItem).toHaveBeenCalledWith(mockDatasetItem.id, {
            base_version: mockDatasetItem.version,
            input: mockDatasetItem.input,
            expected_output: mockDatasetItem.expected_output,
            metadata: mockDatasetItem.metadata,
        })
        expect(mockCloseModal).toHaveBeenCalledWith(true)
    })

    it('offers to reload items when editing an outdated version', async () => {
        const errorDetail = 'This dataset item changed after it was loaded. Reload it and try again.'
        mockDatasetsApi.updateItem.mockRejectedValue(
            new ApiError(errorDetail, 409, undefined, {
                code: CodeEnumApi.StaleVersion,
                detail: errorDetail,
                current_version: 2,
            })
        )
        const logic = datasetItemModalLogic({
            datasetId: 'test-dataset-1',
            partialDatasetItem: mockDatasetItem,
            closeModal: mockCloseModal,
            isModalOpen: true,
        })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.submitDatasetItemForm()
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

        expect(mockCloseModal).toHaveBeenCalledWith(true)
    })

    it('sets correct default form values for new dataset item', () => {
        const logic = datasetItemModalLogic({
            datasetId: 'test-dataset-1',
            partialDatasetItem: null,
            closeModal: mockCloseModal,
            isModalOpen: true,
        })
        logic.mount()

        expect(logic.values.datasetItemForm).toEqual({
            input: EMPTY_JSON,
            expectedOutput: '',
            metadata: EMPTY_JSON,
        })
    })

    it('sets correct default form values for existing dataset item', async () => {
        const logic = datasetItemModalLogic({
            datasetId: 'test-dataset-1',
            partialDatasetItem: mockDatasetItem,
            closeModal: mockCloseModal,
            isModalOpen: true,
        })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.datasetItemForm.input).toContain('"message": "Hello"')
        expect(logic.values.datasetItemForm.expectedOutput).toContain('"response": "Hi there"')
        expect(logic.values.datasetItemForm.metadata).toContain('"source": "test"')
    })

    it('resets form values to default when saving without closing modal', async () => {
        const logic = datasetItemModalLogic({
            datasetId: 'test-dataset-1',
            partialDatasetItem: null,
            closeModal: mockCloseModal,
            isModalOpen: true,
        })
        logic.mount()

        // Set shouldCloseModal to false to trigger "save and add another" behavior
        logic.actions.setShouldCloseModal(false)

        // Set some custom form values
        logic.actions.setDatasetItemFormValues({
            input: '{"custom": "input"}',
            expectedOutput: '{"custom": "output"}',
            metadata: '{"custom": "metadata"}',
        })

        // Verify form has custom values
        expect(logic.values.datasetItemForm).toEqual({
            input: '{"custom": "input"}',
            expectedOutput: '{"custom": "output"}',
            metadata: '{"custom": "metadata"}',
        })

        // Submit form
        await expectLogic(logic, () => {
            logic.actions.submitDatasetItemForm()
        }).toFinishAllListeners()

        expect(logic.values.datasetItemForm).toEqual({
            input: EMPTY_JSON,
            expectedOutput: '',
            metadata: EMPTY_JSON,
        })
    })

    it('preserves arbitrary JSON input and expected output values', async () => {
        const logic = datasetItemModalLogic({
            datasetId: 'test-dataset-1',
            partialDatasetItem: null,
            closeModal: mockCloseModal,
            isModalOpen: true,
        })
        logic.mount()
        logic.actions.setDatasetItemFormValues({
            input: 'false',
            expectedOutput: '["first", 2]',
            metadata: '{}',
        })

        await expectLogic(logic, () => logic.actions.submitDatasetItemForm()).toFinishAllListeners()

        expect(mockDatasetsApi.createItem).toHaveBeenCalledWith({
            dataset: 'test-dataset-1',
            client_item_id: undefined,
            input: false,
            expected_output: ['first', 2],
            source_output: undefined,
            metadata: {},
            source_trace_id: undefined,
            source_event_id: undefined,
            source_timestamp: undefined,
        })
    })

    it('does not submit mutations from a read-only item modal', async () => {
        const logic = datasetItemModalLogic({
            datasetId: 'test-dataset-1',
            partialDatasetItem: mockDatasetItem,
            closeModal: mockCloseModal,
            isModalOpen: true,
            readOnly: true,
        })
        logic.mount()

        await expectLogic(logic, () => logic.actions.submitDatasetItemForm()).toFinishAllListeners()

        expect(mockDatasetsApi.updateItem).not.toHaveBeenCalled()
    })

    it('preserves unsaved changes and prevents restoring a version', async () => {
        const logicProps = {
            datasetId: 'test-dataset-1',
            partialDatasetItem: mockDatasetItem,
            closeModal: mockCloseModal,
            isModalOpen: true,
        }
        const logic = datasetItemModalLogic(logicProps)
        logic.mount()

        logic.actions.setDatasetItemFormValue('input', '{"message": "Changed"}')

        await expectLogic(logic, () => {
            datasetItemModalLogic({ ...logicProps, restoringVersion: 1 })
        })

        expect(logic.values.datasetItemFormChanged).toBe(true)
        expect(logic.values.datasetItemForm.input).toBe('{"message": "Changed"}')
        expect(logic.values.datasetItemVersionRestoreDisabledReason).toBe(
            'Save or discard your changes before restoring a version'
        )
    })

    it('prevents editing and saving while a version is being restored', async () => {
        const logic = datasetItemModalLogic({
            datasetId: 'test-dataset-1',
            partialDatasetItem: mockDatasetItem,
            closeModal: mockCloseModal,
            isModalOpen: true,
            restoringVersion: 1,
        })
        logic.mount()

        expect(logic.values.isDatasetItemFormReadOnly).toBe(true)
        expect(logic.values.datasetItemFormSubmitDisabledReason).toBe('Wait for the version to finish restoring')

        await expectLogic(logic, () => logic.actions.submitDatasetItemForm()).toFinishAllListeners()

        expect(mockDatasetsApi.updateItem).not.toHaveBeenCalled()
    })

    it('updates read-only state when restoring props change', async () => {
        const logicProps = {
            datasetId: 'test-dataset-1',
            partialDatasetItem: mockDatasetItem,
            closeModal: mockCloseModal,
            isModalOpen: true,
        }
        const logic = datasetItemModalLogic(logicProps)
        logic.mount()

        expect(logic.values.isDatasetItemFormReadOnly).toBe(false)
        expect(logic.values.datasetItemFormSubmitDisabledReason).toBeUndefined()

        datasetItemModalLogic({ ...logicProps, restoringVersion: 1 })

        await expectLogic(logic).toMatchValues({
            isDatasetItemFormReadOnly: true,
            datasetItemFormSubmitDisabledReason: 'Wait for the version to finish restoring',
        })

        datasetItemModalLogic({ ...logicProps, restoringVersion: null })

        await expectLogic(logic).toMatchValues({
            isDatasetItemFormReadOnly: false,
            datasetItemFormSubmitDisabledReason: undefined,
        })
    })

    it('rejects invalid expected output JSON', () => {
        expect(isStringJsonValue('{invalid')).toBe(false)
    })
})
