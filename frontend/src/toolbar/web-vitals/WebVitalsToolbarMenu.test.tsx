import '@testing-library/jest-dom'
import { render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'

import { WebVitalsToolbarMenu } from './WebVitalsToolbarMenu'

describe('WebVitalsToolbarMenu', () => {
    beforeEach(() => {
        initKeaTests()
        toolbarConfigLogic
            .build({
                posthog: {
                    config: { ui_host: 'https://us.posthog.com/' },
                    webVitalsAutocapture: { isEnabled: false },
                } as any,
            } as any)
            .mount()
    })

    it('uses the PostHog ui host for the settings link', () => {
        render(<WebVitalsToolbarMenu />)

        const settingsLink = screen.getByRole('link', { name: 'settings page' })
        expect(settingsLink).toHaveAttribute('href', 'https://us.posthog.com/settings/project')
        expect(settingsLink).toHaveAttribute('target', '_blank')
    })
})
