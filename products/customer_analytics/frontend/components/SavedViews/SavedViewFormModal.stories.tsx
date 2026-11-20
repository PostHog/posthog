import type { Meta, StoryObj } from '@storybook/react'
import { kea, path } from 'kea'
import { Form, forms } from 'kea-forms'

import { SavedViewFormModal } from './SavedViewFormModal'

const viewFormLogic = kea([
    path(['stories', 'customerAnalyticsSavedViewForm']),
    forms({ viewForm: { defaults: { name: 'Renewal notes', visibility: 'shared' }, submit: async () => {} } }),
])

const meta: Meta<typeof SavedViewFormModal> = {
    title: 'Customer Analytics/Saved views/Form',
    component: SavedViewFormModal,
    parameters: {
        testOptions: { snapshotTargetSelector: '.LemonModal', waitForSelector: '.LemonModal' },
    },
    args: {
        isOpen: true,
        isEditing: false,
        isSaving: false,
        description: 'Save the current filters and sorting as a reusable view',
        placeholder: 'e.g. Renewal risks',
        onClose: () => {},
        onSubmit: () => {},
        renderForm: (fields) => (
            <Form logic={viewFormLogic} formKey="viewForm">
                {fields}
            </Form>
        ),
    },
}
export default meta

type Story = StoryObj<typeof SavedViewFormModal>
export const Create: Story = {}
export const Edit: Story = { args: { isEditing: true } }
export const Saving: Story = {
    args: { isSaving: true },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
