import { canvasVersionNavigation, shouldClearCanvasBrowse } from './canvasVersionNavigation'

// Newest first, like the versions endpoint: v4 is the latest publish.
const VERSIONS = [{ id: 'v4' }, { id: 'v3' }, { id: 'v2' }, { id: 'v1' }]
const VERSION_IDS = VERSIONS.map((version) => version.id)

describe('canvas version navigation', () => {
    it.each([
        {
            name: 'at the head, undo steps older and there is no redo',
            head: 'v4',
            browse: null,
            expected: { currentIndex: 0, canUndo: true, undoTargetId: 'v3', canRedo: false, redoTargetId: null },
        },
        {
            // Versions newer than a reverted head are reachable by browsing, not by redo.
            name: 'with the head mid-list after a revert, undo steps older and there is no redo',
            head: 'v2',
            browse: null,
            expected: { currentIndex: 2, canUndo: true, undoTargetId: 'v1', canRedo: false, redoTargetId: null },
        },
        {
            name: 'browsing older than the head, undo and redo both step',
            head: 'v4',
            browse: 'v2',
            expected: { currentIndex: 2, canUndo: true, undoTargetId: 'v1', canRedo: true, redoTargetId: 'v3' },
        },
        {
            name: 'at the oldest version, there is no further undo',
            head: 'v4',
            browse: 'v1',
            expected: { currentIndex: 3, canUndo: false, undoTargetId: null, canRedo: true, redoTargetId: 'v2' },
        },
        {
            name: 'redo onto the head ends the browse',
            head: 'v4',
            browse: 'v3',
            expected: { currentIndex: 1, canUndo: true, undoTargetId: 'v2', canRedo: true, redoTargetId: null },
        },
        {
            name: 'browsing newer than a mid-list head, undo steps back toward it and there is no redo',
            head: 'v2',
            browse: 'v3',
            expected: { currentIndex: 1, canUndo: true, undoTargetId: 'v2', canRedo: false, redoTargetId: null },
        },
        {
            name: 'an unknown head falls back to the top',
            head: 'vX',
            browse: null,
            expected: { headIndex: 0, currentIndex: 0 },
        },
        {
            name: 'a missing head falls back to the top',
            head: null,
            browse: null,
            expected: { headIndex: 0, currentIndex: 0 },
        },
        {
            name: 'an unknown browse falls back to the head',
            head: 'v3',
            browse: 'vX',
            expected: { headIndex: 1, currentIndex: 1 },
        },
    ])('$name', ({ head, browse, expected }) => {
        expect(
            canvasVersionNavigation({ versions: VERSIONS, headVersionId: head, browseVersionId: browse })
        ).toMatchObject(expected)
    })

    it('has nothing to step through in an empty history', () => {
        expect(canvasVersionNavigation({ versions: [], headVersionId: null, browseVersionId: null })).toMatchObject({
            canUndo: false,
            canRedo: false,
            undoTargetId: null,
        })
    })

    it.each([
        ['no browse', null, false, VERSION_IDS, false],
        ['a browse still in the list', 'v2', false, VERSION_IDS, false],
        ['a browse pruned from the list', 'vX', false, VERSION_IDS, true],
        ['a history still loading', 'vX', true, VERSION_IDS, false],
        ['an empty target list', 'vX', false, [], false],
        ['a staged draft', 'draft-1', false, [...VERSION_IDS, 'draft-1'], false],
    ])('clears the browse for %s: %s', (_name, browseVersionId, loading, browseTargetIds, expected) => {
        expect(shouldClearCanvasBrowse({ browseTargetIds, loading, browseVersionId })).toBe(expected)
    })
})
