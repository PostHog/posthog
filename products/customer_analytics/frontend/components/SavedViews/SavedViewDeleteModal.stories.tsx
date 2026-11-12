import type { Meta, StoryObj } from '@storybook/react'

import { SavedViewDeleteModal } from './SavedViewDeleteModal'

const meta: Meta<typeof SavedViewDeleteModal> = {
    title: 'Customer Analytics/Saved views/Delete',
    component: SavedViewDeleteModal,
    parameters: {
        testOptions: { snapshotTargetSelector: '.LemonModal', waitForSelector: '.LemonModal' },
    },
    args: { isOpen: true, name: 'Renewal notes', isDeleting: false, onClose: () => {}, onDelete: () => {} },
}
export default meta

type Story = StoryObj<typeof SavedViewDeleteModal>
export const Confirm: Story = {}
export const Deleting: Story = {
    args: { isDeleting: true },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
