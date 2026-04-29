import type { BuiltLogic } from 'kea'
import type { editor } from 'monaco-editor'

import { clearLogicReference, initModel } from 'lib/monaco/CodeEditor'
import type { codeEditorLogicType } from 'lib/monaco/codeEditorLogicType'

const fakeLogic = {} as BuiltLogic<codeEditorLogicType>

const makeFakeModel = (): editor.ITextModel => {
    let disposed = false
    return {
        dispose: () => {
            disposed = true
        },
        isDisposed: () => disposed,
    } as unknown as editor.ITextModel
}

describe('initModel / clearLogicReference', () => {
    it('initModel attaches the logic to the model', () => {
        const model = makeFakeModel()
        initModel(model, fakeLogic)
        expect((model as any).codeEditorLogic).toBe(fakeLogic)
    })

    it('clearLogicReference detaches the logic from the model', () => {
        const model = makeFakeModel()
        initModel(model, fakeLogic)
        clearLogicReference(model)
        expect((model as any).codeEditorLogic).toBeUndefined()
    })

    it('model.dispose() leaves the logic attached — owners must clearLogicReference *before* dispose', () => {
        const model = makeFakeModel()
        initModel(model, fakeLogic)
        model.dispose()
        expect(model.isDisposed()).toBe(true)
        expect((model as any).codeEditorLogic).toBe(fakeLogic)
    })
})
