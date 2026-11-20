import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import * as api from '../../api'
import type { KnowledgeSourceApi } from '../../generated/api.schemas'
import { knowledgeLibraryLogic } from './knowledgeLibraryLogic'

jest.mock('posthog-js', () => ({
    capture: jest.fn(),
}))

jest.mock('../../api', () => ({
    getLibrary: jest.fn(),
    getSource: jest.fn(),
    listSources: jest.fn(),
    updateLibrary: jest.fn(),
    deleteLibrary: jest.fn(),
    updateSource: jest.fn(),
}))

const LIBRARY_ID = 'library-docs'
const OTHER_LIBRARY_ID = 'library-handbook'
const NEW_LIBRARY_ID = 'library-new'

function makeSource(id: string, libraryIds: string[]): KnowledgeSourceApi {
    const source: Partial<KnowledgeSourceApi> = { id, name: id, library_ids: libraryIds }
    return source as KnowledgeSourceApi
}

const IN_LIBRARY = makeSource('source-in', [OTHER_LIBRARY_ID, LIBRARY_ID])
const OUTSIDE = makeSource('source-outside', [OTHER_LIBRARY_ID])

const mockedApi = api as jest.Mocked<typeof api>

describe('knowledgeLibraryLogic', () => {
    let logic: ReturnType<typeof knowledgeLibraryLogic.build>

    beforeEach(async () => {
        jest.clearAllMocks()
        initKeaTests()
        mockedApi.getLibrary.mockResolvedValue({
            id: LIBRARY_ID,
            name: 'Docs',
            is_default: false,
            source_count: 1,
            repos: [],
        })
        mockedApi.listSources.mockImplementation(async (params) =>
            params?.libraryId ? [IN_LIBRARY] : [IN_LIBRARY, OUTSIDE]
        )
        mockedApi.updateSource.mockResolvedValue(IN_LIBRARY)
        logic = knowledgeLibraryLogic({ id: LIBRARY_ID })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('offers only the sources that are not in the library yet', () => {
        expect(logic.values.addableSources).toEqual([OUTSIDE])
    })

    it.each([
        ['adds a source', 'addSource', OUTSIDE.id, [OTHER_LIBRARY_ID, NEW_LIBRARY_ID, LIBRARY_ID]],
        ['removes a source', 'removeSource', IN_LIBRARY.id, [OTHER_LIBRARY_ID, NEW_LIBRARY_ID]],
    ] as const)(
        '%s and keeps a library that another person gave it after the page loaded',
        async (_, action, sourceId, expectedLibraryIds) => {
            const listed = sourceId === OUTSIDE.id ? OUTSIDE : IN_LIBRARY
            mockedApi.getSource.mockResolvedValue(makeSource(sourceId, [...listed.library_ids, NEW_LIBRARY_ID]))

            logic.actions[action](sourceId)
            await expectLogic(logic).toFinishAllListeners()

            expect(mockedApi.updateSource).toHaveBeenCalledWith(sourceId, {
                library_ids: expect.arrayContaining([...expectedLibraryIds]),
            })
            expect(mockedApi.updateSource.mock.calls[0][1].library_ids).toHaveLength(expectedLibraryIds.length)
            expect(logic.values.changingSourceIds).toEqual([])
        }
    )
})
