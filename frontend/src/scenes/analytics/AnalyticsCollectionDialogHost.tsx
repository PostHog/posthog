import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { ShareToSpaceTarget, analyticsShareLogic, shareTargetKey } from './analyticsShareLogic'
import { ShareToSpaceDialog } from './ShareToSpaceDialog'

/**
 * Mounts the collection dialog for a scene and looks up which collection its item is in, so the scene's menu
 * shows the right collection actions as soon as it opens.
 */
export function AnalyticsCollectionDialogHost({
    target: { type, ref, name },
}: {
    target: ShareToSpaceTarget
}): JSX.Element {
    const { itemSpaces } = useValues(analyticsShareLogic)
    const { loadItemSpace } = useActions(analyticsShareLogic)
    const known = shareTargetKey({ type, ref }) in itemSpaces

    useEffect(() => {
        if (!known) {
            loadItemSpace({ type, ref, name })
        }
    }, [known, type, ref, name, loadItemSpace])

    return <ShareToSpaceDialog />
}
