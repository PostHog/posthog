import { ReactNode } from 'react'

import { cn } from 'lib/utils/css-classes'

interface GuidedWizardPanelProps {
    children: ReactNode
    className?: string
}

export function GuidedWizardPanel({ children, className }: GuidedWizardPanelProps): JSX.Element {
    return <div className={cn('rounded-lg border border-border bg-surface-primary p-3', className)}>{children}</div>
}
