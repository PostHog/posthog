import posthog from 'posthog-js'
import type { MouseEvent } from 'react'

export interface AiCitationClickProps {
    onClickCapture: () => void
    onAuxClick: (event: MouseEvent<HTMLElement>) => void
}

// Link skips `onClick` for a Cmd or Ctrl click, and a middle click fires only `auxclick`. Both open the citation.
export function aiCitationClickProps(surface: 'note' | 'panel', isExternal: boolean): AiCitationClickProps {
    const report = (): void => {
        // pinned: analytics event name. Dashboards break when it is renamed.
        posthog.capture('support ai citation clicked', { surface, is_external: isExternal })
    }
    return {
        onClickCapture: report,
        onAuxClick: (event) => {
            if (event.button === 1) {
                report()
            }
        },
    }
}
