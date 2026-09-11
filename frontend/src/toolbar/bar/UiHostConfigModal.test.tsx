import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { FloatingContainerContext } from 'lib/hooks/useFloatingContainerContext'

import { initKeaTests } from '~/test/init'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'

import { UiHostConfigModal } from './UiHostConfigModal'

describe('UiHostConfigModal', () => {
    let container: HTMLDivElement

    beforeEach(() => {
        initKeaTests()
        container = document.createElement('div')
        document.body.append(container)
    })

    afterEach(() => {
        cleanup()
        container.remove()
    })

    const renderModal = (props: Record<string, unknown>): void => {
        toolbarConfigLogic.build(props as any).mount()
        render(
            <FloatingContainerContext.Provider value={container}>
                <UiHostConfigModal visible onClose={() => {}} />
            </FloatingContainerContext.Provider>
        )
    }

    it('names the PostHog app host when one was configured', () => {
        renderModal({
            posthog: { config: { ui_host: 'https://ph.example.com', api_host: 'https://proxy.example.com' } },
        })

        expect(screen.getByText(/tried to connect to the PostHog app at/)).toBeInTheDocument()
        expect(screen.getByText('https://ph.example.com')).toBeInTheDocument()
        expect(screen.getByText(/api_host: 'https:\/\/proxy.example.com'/)).toBeInTheDocument()
    })

    it('stays generic when nothing named the PostHog app', () => {
        // No uiHost prop, no posthog-js config and no apiURL, so the only host left is the page
        // the toolbar runs on. Naming it would tell the user to fix their own domain.
        renderModal({})

        expect(screen.getByText(/could not find the URL of the PostHog app/)).toBeInTheDocument()
        expect(screen.queryByText(/tried to connect to the PostHog app at/)).not.toBeInTheDocument()
        expect(screen.getByText(/api_host: '<your_api_host>'/)).toBeInTheDocument()
    })
})
