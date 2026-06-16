'use client'

import { useSetDockConciergeAgent } from '@/components/dock-context'

export default function AnalyticsLayout({ children }: { children: React.ReactNode }): React.ReactElement {
    useSetDockConciergeAgent({ slug: 'agent-concierge' })
    return <>{children}</>
}
