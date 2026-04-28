import React from 'react'

interface ChartErrorBoundaryProps {
    children: React.ReactNode
    fallback?: React.ReactNode
}

interface ChartErrorBoundaryState {
    hasError: boolean
}

const DEFAULT_FALLBACK_STYLE: React.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: '100%',
    height: '100%',
    minHeight: 100,
    color: 'var(--text-secondary, #666)',
    fontSize: 13,
}

export class ChartErrorBoundary extends React.Component<ChartErrorBoundaryProps, ChartErrorBoundaryState> {
    override state: ChartErrorBoundaryState = { hasError: false }

    static getDerivedStateFromError(): ChartErrorBoundaryState {
        return { hasError: true }
    }

    override componentDidCatch(error: Error, info: React.ErrorInfo): void {
        console.error('[hog-charts] render error:', error, info.componentStack)
    }

    override render(): React.ReactNode {
        if (this.state.hasError) {
            return (
                this.props.fallback ?? (
                    <div style={DEFAULT_FALLBACK_STYLE}>Something went wrong rendering this chart</div>
                )
            )
        }
        return this.props.children
    }
}
