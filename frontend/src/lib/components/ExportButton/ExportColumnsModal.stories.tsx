import { Meta, StoryObj } from '@storybook/react'

import { ExporterFormat } from '~/types'

import { ExportColumnsModal, ExportColumnsModalProps } from './ExportColumnsModal'

const meta: Meta<ExportColumnsModalProps> = {
    title: 'Components/Export Columns Modal',
    component: ExportColumnsModal,
    args: {
        isOpen: true,
        formats: [ExporterFormat.CSV, ExporterFormat.XLSX],
        columns: [
            { name: 'insight_id' },
            { name: 'event' },
            { name: 'timestamp' },
            { name: 'person.id' },
            { name: 'properties.$browser', label: 'Browser' },
        ],
    },
    tags: ['autodocs'],
}
type Story = StoryObj<ExportColumnsModalProps>
export default meta

export const Default: Story = {}

// A daily trend over a long range produces this many columns, which is what the search is for.
export const ManyColumns: Story = {
    args: {
        columns: Array.from({ length: 40 }, (_, index) => ({ name: `${index + 1}-Jan-2026` })),
    },
}
