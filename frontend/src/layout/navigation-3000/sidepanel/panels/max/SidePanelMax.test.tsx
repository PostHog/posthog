import { cleanup, render, screen } from '@testing-library/react'
import { Suspense } from 'react'

import { maxLogic } from 'scenes/max/maxLogic'

import { SIDE_PANEL_PANEL_ID } from '~/layout/ai/aiPanelIds'
import { initKeaTests } from '~/test/init'

import { SidePanelMax } from './SidePanelMax'

jest.mock('scenes/max/Max', () => ({
    MaxInstance: () => <div>side panel chat</div>,
}))

describe('SidePanelMax', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('keeps the side panel chat mounted after the panel closes', async () => {
        // Stands in for the mount the chat UI holds while the panel is open.
        const unmountPanelChat = maxLogic({ panelId: SIDE_PANEL_PANEL_ID }).mount()

        const { unmount } = render(
            <Suspense fallback={null}>
                <SidePanelMax />
            </Suspense>
        )
        await screen.findByText('side panel chat')

        unmount()
        unmountPanelChat()

        expect(maxLogic.findMounted({ panelId: SIDE_PANEL_PANEL_ID })).not.toBeNull()
    })
})
