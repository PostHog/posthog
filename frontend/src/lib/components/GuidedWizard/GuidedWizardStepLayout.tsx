import { ReactNode } from 'react'

import { cn } from 'lib/utils/css-classes'

interface GuidedWizardStepLayoutProps {
    children: ReactNode
    className?: string
}

export function GuidedWizardStepLayout({ children, className }: GuidedWizardStepLayoutProps): JSX.Element {
    return <div className={cn('space-y-5', className)}>{children}</div>
}
