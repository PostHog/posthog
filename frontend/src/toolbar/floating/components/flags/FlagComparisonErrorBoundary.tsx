import { Component, type ReactNode } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { captureToolbarException } from '~/toolbar/shared/toolbarPosthogJS'

interface FlagComparisonErrorBoundaryProps {
    children: ReactNode
}

interface FlagComparisonErrorBoundaryState {
    hasError: boolean
}

/** The floating toolbar has no error boundary of its own, so a failed comparison chunk would unmount the whole toolbar. */
export class FlagComparisonErrorBoundary extends Component<
    FlagComparisonErrorBoundaryProps,
    FlagComparisonErrorBoundaryState
> {
    override state: FlagComparisonErrorBoundaryState = { hasError: false }

    static getDerivedStateFromError(): FlagComparisonErrorBoundaryState {
        return { hasError: true }
    }

    override componentDidCatch(error: unknown): void {
        captureToolbarException(error, 'flag_comparison_render')
    }

    override render(): ReactNode {
        if (this.state.hasError) {
            return <LemonBanner type="error">Couldn't load the comparison. Reload the page and try again.</LemonBanner>
        }
        return this.props.children
    }
}
