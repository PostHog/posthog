import type { Meta, StoryObj } from '@storybook/react'

import { EvaluationReportDrawerToolbar } from './EvaluationReportDrawerToolbar'

const meta: Meta<typeof EvaluationReportDrawerToolbar> = {
    title: 'Scenes-App/AI observability/Evaluation reports/Drawer toolbar',
    component: EvaluationReportDrawerToolbar,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    decorators: [
        (Story) => (
            <div className="w-160 border p-2">
                <Story />
            </div>
        ),
    ],
}
export default meta
type Story = StoryObj<typeof EvaluationReportDrawerToolbar>

const noop = (): void => {}

export const MiddleOfTheList: Story = {
    args: {
        position: { index: 4, total: 20, more: true },
        onPrevious: noop,
        onNext: noop,
        onCopyLink: noop,
        onGenerate: noop,
        onClose: noop,
    },
}

export const NewestWhileWriting: Story = {
    args: {
        position: { index: 0, total: 3, more: false },
        onPrevious: null,
        onNext: noop,
        onCopyLink: noop,
        onGenerate: null,
        generateDisabledReason: 'A new report is being written',
        onClose: noop,
    },
}
