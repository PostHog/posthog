import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { TraceMode } from '../types'
import { TraceModeTabs } from './TraceModeTabs'

function Stateful({ feedbackCount = null }: { feedbackCount?: number | null }): JSX.Element {
    const [mode, setMode] = useState<TraceMode>('spans')
    return <TraceModeTabs mode={mode} onModeChange={setMode} feedbackCount={feedbackCount} />
}

const meta: Meta<typeof Stateful> = {
    title: 'Scenes-App/AI observability/Trace view/Trace mode tabs',
    component: Stateful,
}
export default meta

export const Default: StoryObj<typeof Stateful> = {}
export const WithFeedbackCount: StoryObj<typeof Stateful> = { args: { feedbackCount: 6 } }
