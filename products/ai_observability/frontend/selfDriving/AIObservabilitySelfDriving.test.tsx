import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'
import type { ReactNode } from 'react'

import { initKeaTests } from '~/test/init'

import { AIObservabilitySelfDriving } from './AIObservabilitySelfDriving'

jest.mock('products/signals/frontend/generated/api', () => ({
    signalsScoutConfigList: jest.fn(() => new Promise(() => {})),
    signalsScoutMetadataGet: jest.fn(() => new Promise(() => {})),
}))

jest.mock('products/signals/frontend/inbox/components/config/scouts/ScoutCreateButton', () => ({
    ScoutCreateButton: ({ children }: { children: ReactNode }) => <button>{children}</button>,
}))

describe('AIObservabilitySelfDriving', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('explains the scout pipeline and links to the Inbox', () => {
        render(
            <Provider>
                <AIObservabilitySelfDriving />
            </Provider>
        )

        expect(screen.getAllByText('Use template')).toHaveLength(3)

        const scoutsLink = screen.getByText('Scouts')
        expect(scoutsLink).toHaveAttribute('href', 'https://posthog.com/docs/self-driving/scouts')
        expect(scoutsLink).toHaveAttribute('target', '_blank')

        const pipelineLink = screen.getByText('self-driving pipeline')
        expect(pipelineLink).toHaveAttribute('href', 'https://posthog.com/docs/self-driving/self-improving-loop')
        expect(pipelineLink).toHaveAttribute('target', '_blank')

        expect(screen.getByText('Inbox').getAttribute('href')).toContain('/inbox/reports')
        expect(screen.getByText(/Actionable scout reports appear in your/)).toBeInTheDocument()
        expect(screen.getByText('ai-observability').closest('p')).toHaveTextContent(
            'Add the ai-observability label to a scout for it to appear here.'
        )
    })
})
