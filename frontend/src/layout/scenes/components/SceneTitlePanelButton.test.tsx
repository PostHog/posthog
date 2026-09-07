import '@testing-library/jest-dom'

import { cleanup, fireEvent, render } from '@testing-library/react'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { SceneTitlePanelButton } from './SceneTitleSection'

describe('SceneTitlePanelButton', () => {
    beforeEach(() => {
        initKeaTests()
        jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
    })
    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    // Without this event a click that never reaches `openSidePanel` leaves no trace at all,
    // so the panel-never-opens failure has no denominator.
    test('captures a click on the PostHog AI button', () => {
        render(<SceneTitlePanelButton />)

        fireEvent.click(document.querySelector('[data-attr="open-context-panel-ai-button"]') as HTMLElement)

        expect(posthog.capture).toHaveBeenCalledWith('scene ai button clicked', expect.objectContaining({ tool: null }))
    })
})
