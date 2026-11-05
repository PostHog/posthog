import type { Meta, StoryObj } from '@storybook/react'

import { withWidth } from '../storyFixtures'
import { TraceDrawerToolbar } from './TraceDrawerToolbar'

const meta: Meta<typeof TraceDrawerToolbar> = {
    title: 'Scenes-App/AI observability/Trace view/Trace drawer toolbar',
    component: TraceDrawerToolbar,
    decorators: [withWidth(640)],
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        position: { index: 1, total: 12 },
        onPrevious: () => {},
        onNext: () => {},
        fullPageHref: '/traces/trace-1',
        onClose: () => {},
    },
}
export default meta

type Story = StoryObj<typeof TraceDrawerToolbar>

export const Default: Story = {}
export const FirstTrace: Story = { args: { position: { index: 0, total: 12 }, onPrevious: null } }
export const NotInList: Story = { args: { position: null, onPrevious: null, onNext: null } }
export const Narrow: Story = { decorators: [withWidth(480)] }
