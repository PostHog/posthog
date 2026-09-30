import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { ThreadSkin } from 'products/posthog_ai/frontend/api/primitives'

/** The quill chat is part of the quill web redesign, so `today-rail-nav` turns it on as well. */
export function useThreadSkin(): ThreadSkin {
    const phaiQuill = useFeatureFlag('PHAI_QUILL')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    return phaiQuill || todayRailNav ? 'quill' : 'lemon'
}
