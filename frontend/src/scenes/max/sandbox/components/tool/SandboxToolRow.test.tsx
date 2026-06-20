import '@testing-library/jest-dom'

import { fireEvent, render, screen } from '@testing-library/react'

import { IconWrench } from '@posthog/icons'

import { SandboxToolRow } from './SandboxToolRow'

describe('SandboxToolRow', () => {
    it('renders a string header and keeps the body collapsed until the header is clicked', () => {
        render(
            <SandboxToolRow icon={<IconWrench />} content={<div>body content</div>}>
                Header label
            </SandboxToolRow>
        )

        expect(screen.getByText('Header label')).toBeInTheDocument()
        expect(screen.queryByText('body content')).not.toBeInTheDocument()

        fireEvent.click(screen.getByRole('button'))
        expect(screen.getByText('body content')).toBeInTheDocument()
    })

    it('expands the body immediately when defaultOpen is set', () => {
        render(
            <SandboxToolRow icon={<IconWrench />} defaultOpen content={<div>visible now</div>}>
                Header
            </SandboxToolRow>
        )
        expect(screen.getByText('visible now')).toBeInTheDocument()
    })

    it('surfaces failed and cancelled markers', () => {
        const { rerender } = render(
            <SandboxToolRow icon={<IconWrench />} isFailed>
                Header
            </SandboxToolRow>
        )
        expect(screen.getByText('(Failed)')).toBeInTheDocument()

        rerender(
            <SandboxToolRow icon={<IconWrench />} wasCancelled>
                Header
            </SandboxToolRow>
        )
        expect(screen.getByText('(Cancelled)')).toBeInTheDocument()
    })

    it('shows the error line in the body when failed', () => {
        render(
            <SandboxToolRow icon={<IconWrench />} isFailed errorMessage="it broke" defaultOpen>
                Header
            </SandboxToolRow>
        )
        expect(screen.getByText('it broke')).toBeInTheDocument()
    })

    it('renders the debug details slot when expanded', () => {
        render(
            <SandboxToolRow icon={<IconWrench />} defaultOpen debugDetails={<div>debug panel</div>}>
                Header
            </SandboxToolRow>
        )
        expect(screen.getByText('debug panel')).toBeInTheDocument()
    })
})
