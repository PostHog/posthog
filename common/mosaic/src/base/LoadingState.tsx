import type { ReactElement } from 'react'

export interface LoadingStateProps {
    label: string
}

export function LoadingState({ label }: LoadingStateProps): ReactElement {
    return (
        <div className="flex flex-col items-center justify-center py-12 gap-3">
            <div className="h-5 w-5 rounded-full border-2 border-text-secondary border-t-transparent animate-spin" />
            <span className="text-sm text-text-secondary">Loading {label}...</span>
        </div>
    )
}
