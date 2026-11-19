import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'
import type { TeamType } from '~/types'

import * as api from '../../api'
import { businessKnowledgeKeysList } from '../../generated/api'
import { librariesLogic } from './librariesLogic'

jest.mock('posthog-js', () => ({
    capture: jest.fn(),
}))

jest.mock('../../api', () => ({
    listLibraries: jest.fn(),
    createLibrary: jest.fn(),
}))

jest.mock('../../generated/api', () => ({
    businessKnowledgeKeysList: jest.fn(),
}))

const DOCS = { id: 'library-docs', name: 'Docs', is_default: false, source_count: 4, repos: ['acme/docs'] }
const KEY = {
    label: 'Agent',
    mask_value: 'phs_...example',
    value: null,
    created_at: '2026-01-01T00:00:00Z',
    last_used_at: null,
}
const KEYS = [
    { ...KEY, id: 'key-docs', is_limited: true, library_id: DOCS.id },
    { ...KEY, id: 'key-all', is_limited: false, library_id: null },
    { ...KEY, id: 'key-orphan', is_limited: true, library_id: null },
]

const mockedApi = api as jest.Mocked<typeof api>

describe('librariesLogic', () => {
    let logic: ReturnType<typeof librariesLogic.build>

    async function mountIn(environment: 'main' | 'child'): Promise<void> {
        initKeaTests()
        teamLogic.mount()
        const team = teamLogic.values.currentTeam as TeamType
        teamLogic.actions.loadCurrentTeamSuccess({
            ...team,
            project_id: environment === 'main' ? team.id : team.id + 1,
        })
        logic = librariesLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        jest.clearAllMocks()
        mockedApi.listLibraries.mockResolvedValue([DOCS])
        ;(businessKnowledgeKeysList as jest.Mock).mockResolvedValue(KEYS)
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('counts the keys for each library and for all business knowledge', async () => {
        await mountIn('main')

        expect(logic.values.rows.map((row) => [row.name, row.keyCount])).toEqual([
            ['All business knowledge', 1],
            ['Docs', 1],
        ])
    })

    it('lists the libraries without key counts and without a key request in a child environment', async () => {
        await mountIn('child')

        expect(businessKnowledgeKeysList).not.toHaveBeenCalled()
        expect(logic.values.rows.map((row) => [row.name, row.keyCount])).toEqual([['Docs', null]])
    })

    it('opens the new library after it is created', async () => {
        await mountIn('main')
        mockedApi.createLibrary.mockResolvedValue({ ...DOCS, id: 'library-new', name: 'Support' })

        logic.actions.createLibrary('Support')
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.location.pathname).toContain('/business-knowledge/libraries/library-new')
        expect(logic.values.creating).toBe(false)
    })
})
