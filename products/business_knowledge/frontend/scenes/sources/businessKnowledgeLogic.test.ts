import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import * as api from '../../api'
import type { KnowledgeSourceApi } from '../../generated/api.schemas'
import { businessKnowledgeLogic } from './businessKnowledgeLogic'

jest.mock('posthog-js', () => ({
    capture: jest.fn(),
}))

jest.mock('../../api', () => ({
    listSources: jest.fn(),
    listLibraries: jest.fn(),
    createLibrary: jest.fn(),
    updateLibrary: jest.fn(),
    deleteLibrary: jest.fn(),
    updateSource: jest.fn(),
    createTextSource: jest.fn(),
    createUrlSource: jest.fn(),
    createFileSource: jest.fn(),
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

const MOCK_SOURCE: KnowledgeSourceApi = {
    id: '11111111-1111-1111-1111-111111111111',
    team_id: 1,
    name: 'Refund policy',
    source_type: 'text',
    is_generated: true,
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
    learned_from_ticket_number: 42,
    learned_from_ticket_url: null,
    crawl_mode: 'single',
    crawl_config: {},
    original_filename: '',
    file_content_type: '',
    file_size_bytes: null,
    always_include: false,
    library_ids: [],
}

const mockedApi = api as jest.Mocked<typeof api>

describe('businessKnowledgeLogic', () => {
    let logic: ReturnType<typeof businessKnowledgeLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        jest.clearAllMocks()
        mockedApi.listSources.mockResolvedValue([MOCK_SOURCE])
        mockedApi.listLibraries.mockResolvedValue([])
        logic = businessKnowledgeLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('reloads the sources with the added-by filter and combines it with the type filter', async () => {
        await expectLogic(logic, () => {
            logic.actions.setAddedByFilter('learned')
        })
            .toDispatchActions(['setAddedByFilter', 'loadSources', 'loadSourcesSuccess'])
            .toMatchValues({ addedByFilter: 'learned' })

        expect(mockedApi.listSources).toHaveBeenLastCalledWith({
            search: '',
            sourceType: 'all',
            addedBy: 'learned',
            libraryId: undefined,
            unfiled: false,
        })

        await expectLogic(logic, () => {
            logic.actions.setSourceTypeFilter('text')
        }).toDispatchActions(['loadSourcesSuccess'])

        expect(mockedApi.listSources).toHaveBeenLastCalledWith({
            search: '',
            sourceType: 'text',
            addedBy: 'learned',
            libraryId: undefined,
            unfiled: false,
        })
    })

    it('selects a library from the url and lists its sources', async () => {
        const libraryId = '22222222-2222-2222-2222-222222222222'
        logic.unmount()
        mockedApi.listLibraries.mockResolvedValue([
            { id: libraryId, name: 'Docs', is_default: false, source_count: 1, repos: [] },
        ])
        router.actions.push('/business-knowledge', { library: libraryId })
        logic = businessKnowledgeLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.libraryScope).toEqual(libraryId)
        expect(mockedApi.listSources).toHaveBeenLastCalledWith({
            search: '',
            sourceType: 'all',
            addedBy: 'all',
            libraryId,
            unfiled: false,
        })
    })

    it('falls back to all when the url library is unknown', async () => {
        logic.unmount()
        mockedApi.listLibraries.mockResolvedValue([
            { id: '33333333-3333-3333-3333-333333333333', name: 'Docs', is_default: false, source_count: 0, repos: [] },
        ])
        router.actions.push('/business-knowledge', { library: '44444444-4444-4444-4444-444444444444' })
        logic = businessKnowledgeLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.libraryScope).toEqual('all')
        expect(mockedApi.listSources).toHaveBeenLastCalledWith({
            search: '',
            sourceType: 'all',
            addedBy: 'all',
            libraryId: undefined,
            unfiled: false,
        })
    })

    it('returns to all after the selected library is deleted', async () => {
        const libraryId = '22222222-2222-2222-2222-222222222222'
        mockedApi.listLibraries.mockResolvedValue([
            { id: libraryId, name: 'Docs', is_default: false, source_count: 1, repos: [] },
        ])
        mockedApi.deleteLibrary.mockResolvedValue(undefined)
        await expectLogic(logic, () => {
            logic.actions.setLibraryScope(libraryId)
        }).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.deleteSelectedLibrary()
        }).toFinishAllListeners()

        expect(logic.values.libraryScope).toEqual('all')
    })

    it('selects a new library while other libraries exist', async () => {
        const existing = {
            id: '22222222-2222-2222-2222-222222222222',
            name: 'Docs',
            is_default: false,
            source_count: 1,
            repos: [],
        }
        const created = {
            id: '33333333-3333-3333-3333-333333333333',
            name: 'Support',
            is_default: false,
            source_count: 0,
            repos: [],
        }
        mockedApi.listLibraries.mockResolvedValue([existing])
        await expectLogic(logic, () => {
            logic.actions.loadLibraries()
        }).toFinishAllListeners()
        mockedApi.createLibrary.mockResolvedValue(created)
        mockedApi.listLibraries.mockResolvedValue([existing, created])

        await expectLogic(logic, () => {
            logic.actions.createLibrary('Support')
        }).toFinishAllListeners()

        expect(logic.values.libraryScope).toEqual(created.id)
    })

    it('files a new source into the selected library when the modal closes mid-request', async () => {
        const libraryId = '22222222-2222-2222-2222-222222222222'
        mockedApi.listLibraries.mockResolvedValue([
            { id: libraryId, name: 'Docs', is_default: false, source_count: 0, repos: [] },
        ])
        let resolveCreate: (source: KnowledgeSourceApi) => void = () => undefined
        mockedApi.createTextSource.mockReturnValue(
            new Promise((resolve) => {
                resolveCreate = resolve
            })
        )
        mockedApi.updateSource.mockResolvedValue({ ...MOCK_SOURCE, library_ids: [libraryId] })
        await expectLogic(logic, () => {
            logic.actions.setLibraryScope(libraryId)
            logic.actions.openCreateModal()
        }).toFinishAllListeners()
        expect(logic.values.createLibraryIds).toEqual([libraryId])

        logic.actions.setTextSourceValue('name', 'Policy')
        logic.actions.setTextSourceValue('text', 'Refunds are available within 30 days.')
        await expectLogic(logic, () => {
            logic.actions.submitTextSource()
        }).toDispatchActions(['submitTextSourceRequest'])
        expect(mockedApi.createTextSource).toHaveBeenCalled()
        logic.actions.closeCreateModal()
        expect(logic.values.createLibraryIds).toEqual([])
        resolveCreate(MOCK_SOURCE)
        await expectLogic(logic).toFinishAllListeners()

        expect(mockedApi.updateSource).toHaveBeenCalledWith(MOCK_SOURCE.id, { library_ids: [libraryId] })
    })

    it('keeps the persisted filters apart per team', () => {
        logic.actions.setAddedByFilter('human')
        logic.unmount()

        const otherTeam = { ...(window.POSTHOG_APP_CONTEXT as any).current_team, id: 4242 }
        initKeaTests(true, otherTeam)
        logic = businessKnowledgeLogic()
        logic.mount()

        expect(logic.values.addedByFilter).toEqual('all')
    })
})
