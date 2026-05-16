import { shouldWarnBeforeLeavingNotebook } from './notebookBeforeUnload'

describe('shouldWarnBeforeLeavingNotebook', () => {
    const baseInput = {
        mode: 'notebook' as const,
        isLocalOnly: false,
        isShared: false,
        isEditable: true,
        syncStatus: 'unsaved' as const,
        currentPathname: '/project/1/notebooks/abc',
    }

    it.each([
        ['unsaved', 'unsaved' as const, true],
        ['saving (in flight, including 409 retry loop)', 'saving' as const, true],
        ['synced', 'synced' as const, false],
        ['local', 'local' as const, false],
    ])('warns when syncStatus is %s -> %s', (_label, syncStatus, expected) => {
        expect(shouldWarnBeforeLeavingNotebook({ ...baseInput, syncStatus })).toBe(expected)
    })

    it('does not warn for canvas mode', () => {
        expect(shouldWarnBeforeLeavingNotebook({ ...baseInput, mode: 'canvas' })).toBe(false)
    })

    it('does not warn for local-only notebooks (scratchpad / template)', () => {
        expect(shouldWarnBeforeLeavingNotebook({ ...baseInput, isLocalOnly: true })).toBe(false)
    })

    it('does not warn for shared / read-only views', () => {
        expect(shouldWarnBeforeLeavingNotebook({ ...baseInput, isShared: true })).toBe(false)
    })

    it('does not warn when the notebook is not editable for the current user', () => {
        expect(shouldWarnBeforeLeavingNotebook({ ...baseInput, isEditable: false })).toBe(false)
    })

    it('does not warn for in-page URL updates (same pathname)', () => {
        expect(
            shouldWarnBeforeLeavingNotebook({
                ...baseInput,
                newPathname: '/project/1/notebooks/abc',
            })
        ).toBe(false)
    })

    it('warns when navigating to a different pathname', () => {
        expect(
            shouldWarnBeforeLeavingNotebook({
                ...baseInput,
                newPathname: '/project/1/dashboard',
            })
        ).toBe(true)
    })

    it('warns when no newPathname is provided (browser tab close)', () => {
        expect(shouldWarnBeforeLeavingNotebook(baseInput)).toBe(true)
    })
})
