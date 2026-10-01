import type { CanvasSourceProjectApi } from '../generated/api.schemas'
import {
    CanvasSourceEntry,
    applySourceFiles,
    isSourceDirty,
    loadSourceEntry,
    redoSourceEntry,
    resolveSourceConflict,
    setSourceConflict,
    undoSourceEntry,
} from './canvasSourceSnapshots'

const PROJECT: CanvasSourceProjectApi = {
    schemaVersion: 1,
    entryHtml: 'index.html',
    files: { 'src/canvas.tsx': 'saved' },
    dependencies: {},
}

function conflicted(): CanvasSourceEntry {
    const loaded = loadSourceEntry(null, PROJECT, 'v1')
    return setSourceConflict(applySourceFiles(loaded, { 'src/canvas.tsx': 'local edit' }), 'v2')
}

describe('canvasSourceSnapshots', () => {
    it.each([
        { keepLocal: true, base: 'v2', files: { 'src/canvas.tsx': 'local edit' }, dirty: true },
        { keepLocal: false, base: 'v1', files: { 'src/canvas.tsx': 'saved' }, dirty: false },
    ])('keepLocal=$keepLocal publishes over v2 only when chosen', ({ keepLocal, base, files, dirty }) => {
        const entry = resolveSourceConflict(conflicted(), keepLocal)
        expect(entry.conflict).toBeNull()
        expect(entry.baseVersionId).toBe(base)
        expect(entry.files).toEqual(files)
        expect(isSourceDirty(entry)).toBe(dirty)
    })

    it('drops undo history when a newer version loads', () => {
        expect(loadSourceEntry(conflicted(), PROJECT, 'v2').past).toEqual([])
    })

    it('redoes an undone edit until a new edit replaces it', () => {
        const edited = applySourceFiles(loadSourceEntry(null, PROJECT, 'v1'), { 'src/canvas.tsx': 'first' })
        const undone = undoSourceEntry(edited)
        expect(undone.files).toEqual({ 'src/canvas.tsx': 'saved' })
        expect(redoSourceEntry(undone).files).toEqual({ 'src/canvas.tsx': 'first' })
        expect(applySourceFiles(undone, { 'src/canvas.tsx': 'second' }).future).toEqual([])
    })
})
