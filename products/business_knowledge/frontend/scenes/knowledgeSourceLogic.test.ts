import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import * as api from '../api'
import type { KnowledgeSourceApi } from '../generated/api.schemas'
import { knowledgeSourceLogic } from './knowledgeSourceLogic'

jest.mock('../api', () => ({
    getSource: jest.fn(),
    getSourceText: jest.fn(),
    getSourceDocuments: jest.fn(),
    updateSource: jest.fn(),
    deleteSource: jest.fn(),
    refreshSource: jest.fn(),
}))

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: {
        success: jest.fn(),
        error: jest.fn(),
        info: jest.fn(),
    },
}))

const SOURCE_ID = '11111111-1111-1111-1111-111111111111'

const MOCK_SOURCE: KnowledgeSourceApi = {
    id: SOURCE_ID,
    team_id: 1,
    name: 'Refund policy',
    source_type: 'text',
    is_generated: false,
    status: 'ready',
    error_message: '',
    document_count: 1,
    chunk_count: 3,
    created_at: '2026-09-01T12:00:00Z',
    updated_at: '2026-09-01T12:00:00Z',
    source_url: '',
    last_refresh_at: null,
    last_refresh_status: 'success',
    last_refresh_error: '',
    refresh_interval: 'manual',
    next_refresh_at: null,
    has_unsafe_documents: false,
    embedding_status: 'completed',
    learned_from_ticket_number: null,
    learned_from_ticket_url: null,
    crawl_mode: 'single',
    crawl_config: {},
    original_filename: '',
    file_content_type: '',
    file_size_bytes: null,
    always_include: false,
}

const mockedApi = api as jest.Mocked<typeof api>

describe('knowledgeSourceLogic', () => {
    let logic: ReturnType<typeof knowledgeSourceLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        mockedApi.getSource.mockResolvedValue(MOCK_SOURCE)
        mockedApi.getSourceText.mockResolvedValue({ id: SOURCE_ID, text: 'Refund within 30 days.' })
        mockedApi.getSourceDocuments.mockResolvedValue([])
        mockedApi.updateSource.mockResolvedValue({ ...MOCK_SOURCE, name: 'Updated policy', chunk_count: 4 })
        mockedApi.deleteSource.mockResolvedValue(undefined)
        logic = knowledgeSourceLogic({ id: SOURCE_ID })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('marks the source not found on a 404 without throwing', async () => {
        logic.unmount()
        mockedApi.getSource.mockRejectedValue({ status: 404, detail: 'Not found.' })
        logic = knowledgeSourceLogic({ id: SOURCE_ID })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({
            source: null,
            sourceNotFound: true,
            sourceLoading: false,
        })
    })

    it('stays on the page after a successful save', async () => {
        const pushSpy = jest.spyOn(router.actions, 'push')

        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.editSource.text).toBe('Refund within 30 days.')
        expect(logic.values.editSourceChanged).toBe(false)

        logic.actions.setEditSourceValues({
            name: 'Updated policy',
            text: 'Refund within 60 days.',
            always_include: false,
        })

        await expectLogic(logic, () => {
            logic.actions.submitEditSource()
        }).toFinishAllListeners()

        expect(mockedApi.updateSource).toHaveBeenCalledWith(
            SOURCE_ID,
            expect.objectContaining({ name: 'Updated policy', text: 'Refund within 60 days.' })
        )
        expect(logic.values.editSource.text).toBe('Refund within 60 days.')
        expect(logic.values.editSourceChanged).toBe(false)
        expect(pushSpy).not.toHaveBeenCalled()
        expect(mockedApi.getSource).toHaveBeenCalled()
        expect(mockedApi.getSourceDocuments).not.toHaveBeenCalled()
        pushSpy.mockRestore()
    })

    it('keeps an edit made while the save is in flight', async () => {
        let resolveUpdate: (source: KnowledgeSourceApi) => void = () => {}
        mockedApi.updateSource.mockReturnValue(new Promise((resolve) => (resolveUpdate = resolve)))

        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setEditSourceValue('name', 'Updated policy')
        logic.actions.submitEditSource()
        logic.actions.setEditSourceValue('name', 'Edited during save')
        resolveUpdate({ ...MOCK_SOURCE, name: 'Updated policy' })
        await expectLogic(logic).toFinishAllListeners()

        expect(mockedApi.updateSource).toHaveBeenCalledWith(
            SOURCE_ID,
            expect.objectContaining({ name: 'Updated policy' })
        )
        expect(logic.values.editSource.name).toBe('Edited during save')
        expect(logic.values.editSourceChanged).toBe(true)
    })

    it('does not treat a server error as not found', async () => {
        logic.unmount()
        mockedApi.getSource.mockRejectedValue({ status: 500, detail: 'boom' })
        logic = knowledgeSourceLogic({ id: SOURCE_ID })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({
            source: null,
            sourceNotFound: false,
            sourceLoading: false,
        })
    })

    it('does not reset in-progress edits when the source is polled', async () => {
        logic.unmount()
        mockedApi.getSource.mockResolvedValue({
            ...MOCK_SOURCE,
            source_type: 'url',
            status: 'processing',
            source_url: 'https://docs.example.com',
        })
        logic = knowledgeSourceLogic({ id: SOURCE_ID })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.editUrlSourceChanged).toBe(false)

        logic.actions.setEditUrlSourceValue('name', 'Draft name')

        await expectLogic(logic, () => {
            logic.actions.loadSource()
        }).toFinishAllListeners()

        expect(logic.values.editUrlSource.name).toBe('Draft name')
        expect(logic.values.editUrlSourceChanged).toBe(true)
        expect(mockedApi.getSourceDocuments).toHaveBeenCalledWith(SOURCE_ID)
        expect(logic.values.sourceDocumentsLoaded).toBe(true)
    })

    it('keeps the source when the indexed page list fails', async () => {
        logic.unmount()
        mockedApi.getSource.mockResolvedValue({
            ...MOCK_SOURCE,
            source_type: 'url',
            status: 'ready',
            source_url: 'https://docs.example.com',
        })
        mockedApi.getSourceDocuments.mockRejectedValue({ status: 500, detail: 'boom' })
        logic = knowledgeSourceLogic({ id: SOURCE_ID })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({
            sourceNotFound: false,
            sourceDocumentsFailed: true,
            sourceDocumentsLoaded: false,
            sourceDocuments: [],
        })
        expect(logic.values.source?.id).toBe(SOURCE_ID)
    })

    it('still opens the text form if content fails to load', async () => {
        logic.unmount()
        mockedApi.getSourceText.mockRejectedValue({ status: 500, detail: 'boom' })
        mockedApi.updateSource.mockResolvedValue({ ...MOCK_SOURCE, name: 'Renamed policy', always_include: true })
        logic = knowledgeSourceLogic({ id: SOURCE_ID })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({
            sourceTextFailed: true,
            isSourceTextReady: true,
        })

        logic.actions.setEditSourceValues({ name: 'Renamed policy', always_include: true })

        await expectLogic(logic, () => {
            logic.actions.submitEditSource()
        }).toFinishAllListeners()

        expect(mockedApi.updateSource).toHaveBeenCalledWith(SOURCE_ID, {
            name: 'Renamed policy',
            always_include: true,
        })
    })

    it('navigates to the list after delete', async () => {
        const pushSpy = jest.spyOn(router.actions, 'push')

        await expectLogic(logic, () => {
            logic.actions.deleteSource()
        }).toFinishAllListeners()

        expect(mockedApi.deleteSource).toHaveBeenCalledWith(SOURCE_ID)
        expect(pushSpy).toHaveBeenCalledWith('/business-knowledge')
        pushSpy.mockRestore()
    })
})
