import { initKeaTests } from '~/test/init'

import { lemonDialogLogic } from './lemonDialogLogic'

describe('lemonDialogLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('isolates form state and validation between dialogs with different keys', () => {
        const saveView = lemonDialogLogic({
            dialogKey: 'save-view',
            errors: { viewName: (name: string) => (/\s/.test(name ?? '') ? 'Spaces are not allowed' : undefined) },
        })
        saveView.mount()
        saveView.actions.setFormValues({ viewName: 'invalid name' })
        expect(saveView.values.isFormValid).toBe(false)

        const newFolder = lemonDialogLogic({
            dialogKey: 'new-folder',
            errors: { folderName: (name: string) => (!name?.trim() ? 'You must enter a folder name' : undefined) },
        })
        newFolder.mount()
        newFolder.actions.setFormValues({ folderName: 'docs' })
        expect(newFolder.values.isFormValid).toBe(true)

        // The nested dialog's valid form must not leak into the parent's validation.
        expect(saveView.values.isFormValid).toBe(false)
        expect(saveView.values.form).toEqual({ viewName: 'invalid name' })

        newFolder.unmount()
        saveView.unmount()
    })

    it('shares state when no key is provided, falling back to a single default instance', () => {
        const first = lemonDialogLogic({ errors: {} })
        first.mount()
        const second = lemonDialogLogic({ errors: {} })
        second.mount()

        first.actions.setFormValues({ name: 'shared' })
        expect(second.values.form).toEqual({ name: 'shared' })

        second.unmount()
        first.unmount()
    })
})
