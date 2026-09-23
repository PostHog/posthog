import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import * as api from '../api'
import type { KnowledgeSourceApi } from '../generated/api.schemas'
import { businessKnowledgeLogic } from './businessKnowledgeLogic'

jest.mock('../api', () => ({
    listSources: jest.fn(),
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
}

const mockedApi = api as jest.Mocked<typeof api>

describe('businessKnowledgeLogic', () => {
    let logic: ReturnType<typeof businessKnowledgeLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        jest.clearAllMocks()
        mockedApi.listSources.mockResolvedValue([MOCK_SOURCE])
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
        })

        await expectLogic(logic, () => {
            logic.actions.setSourceTypeFilter('text')
        }).toDispatchActions(['loadSourcesSuccess'])

        expect(mockedApi.listSources).toHaveBeenLastCalledWith({
            search: '',
            sourceType: 'text',
            addedBy: 'learned',
        })
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
