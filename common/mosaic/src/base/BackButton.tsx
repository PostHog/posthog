import type { ReactElement } from 'react'

export interface BackButtonProps {
    onClick: () => void
    label?: string
}

export function BackButton({ onClick, label = 'Back' }: BackButtonProps): ReactElement {
    return (
        <button
            onClick={onClick}
            className="flex items-center gap-1 text-sm text-text-secondary hover:text-text-primary cursor-pointer transition-colors"
        >
            <span>&larr;</span>
            <span>{label}</span>
        </button>
    )
}
