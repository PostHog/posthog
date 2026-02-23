import { useContext } from 'react'

import { HogSenseBanner } from './HogSenseBanner'
import { HogSenseContext } from './HogSenseContext'
import { HogSenseHint } from './HogSenseHint'
import type { Finding, HogSenseDisplay } from './types'

const DISPLAY_COMPONENTS: Record<HogSenseDisplay, React.ComponentType<{ finding: Finding; className?: string }>> = {
    banner: HogSenseBanner,
    hint: HogSenseHint,
}

export function HogSensePosition({ name, className }: { name: string; className?: string }): JSX.Element | null {
    const ctx = useContext(HogSenseContext)
    if (!ctx) {
        return null
    }
    const entries = ctx.renderMap[name]
    if (!entries?.length) {
        return null
    }
    const elements: JSX.Element[] = []
    for (const entry of entries) {
        const matched = ctx.findings.filter((f) => entry.ids.includes(f.id))
        const Component = DISPLAY_COMPONENTS[entry.display]
        for (const finding of matched) {
            elements.push(<Component key={finding.id} finding={finding} className={entry.className} />)
        }
    }
    if (elements.length === 0) {
        return null
    }
    if (className) {
        return <div className={className}>{elements}</div>
    }
    return <>{elements}</>
}
