import { MAX_FIND_SEARCH_STRING_LENGTH, limitFindSearchString } from 'lib/monaco/limitFindSearchString'

describe('limitFindSearchString', () => {
    const buildEditor = (): { editor: any; changes: any[] } => {
        const changes: any[] = []
        const state = {
            change: (newState: any, moveCursor: boolean, updateHistory?: boolean) => {
                changes.push({ newState, moveCursor, updateHistory })
            },
        }
        return { editor: { getContribution: () => ({ getState: () => state }) }, changes }
    }

    it.each([
        [
            'an oversized search string is cut to the cap',
            MAX_FIND_SEARCH_STRING_LENGTH + 1,
            MAX_FIND_SEARCH_STRING_LENGTH,
        ],
        ['a search string at the cap is left alone', MAX_FIND_SEARCH_STRING_LENGTH, MAX_FIND_SEARCH_STRING_LENGTH],
        ['a short search string is left alone', 12, 12],
    ])('%s', (_name, seeded, expectedLength) => {
        const { editor, changes } = buildEditor()

        limitFindSearchString(editor)
        editor
            .getContribution()
            .getState()
            .change({ searchString: 'a'.repeat(seeded), isRevealed: true }, false)

        expect(changes).toHaveLength(1)
        expect(changes[0].newState.searchString).toHaveLength(expectedLength)
        expect(changes[0].newState.isRevealed).toBe(true)
        expect(changes[0].moveCursor).toBe(false)
    })

    it.each([
        [
            'a cut inside an escape pair drops the dangling backslash',
            `${'a'.repeat(MAX_FIND_SEARCH_STRING_LENGTH - 1)}\\.`,
            MAX_FIND_SEARCH_STRING_LENGTH - 1,
        ],
        [
            'a cut after a complete escape pair keeps both characters',
            `${'a'.repeat(MAX_FIND_SEARCH_STRING_LENGTH - 2)}\\\\ab`,
            MAX_FIND_SEARCH_STRING_LENGTH,
        ],
    ])('%s', (_name, seeded, expectedLength) => {
        const { editor, changes } = buildEditor()

        limitFindSearchString(editor)
        editor.getContribution().getState().change({ searchString: seeded }, false)

        const searchString = changes[0].newState.searchString
        expect(searchString).toHaveLength(expectedLength)
        expect(seeded.startsWith(searchString)).toBe(true)
        expect(() => new RegExp(searchString)).not.toThrow()
    })

    it('leaves a change without a search string untouched', () => {
        const { editor, changes } = buildEditor()

        limitFindSearchString(editor)
        editor.getContribution().getState().change({ isRevealed: false }, true, false)

        expect(changes).toEqual([{ newState: { isRevealed: false }, moveCursor: true, updateHistory: false }])
    })

    it('stops capping once disposed', () => {
        const { editor, changes } = buildEditor()
        const oversized = 'a'.repeat(MAX_FIND_SEARCH_STRING_LENGTH + 1)

        limitFindSearchString(editor).dispose()
        editor.getContribution().getState().change({ searchString: oversized }, false)

        expect(changes[0].newState.searchString).toHaveLength(oversized.length)
    })

    it('does nothing when the find controller is missing', () => {
        expect(() => limitFindSearchString({ getContribution: () => null } as any).dispose()).not.toThrow()
    })
})
