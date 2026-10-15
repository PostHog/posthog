import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { QuillTransitionContext } from './QuillTransitionContext'

export function QuillTransitionProvider({ children }: { children: React.ReactNode }): JSX.Element {
    const enabled = useFeatureFlag('TODAY_RAIL_NAV')
    return <QuillTransitionContext.Provider value={enabled}>{children}</QuillTransitionContext.Provider>
}
