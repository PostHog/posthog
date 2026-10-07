import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonBannerAction } from 'lib/lemon-ui/LemonBanner/LemonBanner'

import { FlagCalledReferences, dependsOnFlagCalls } from './flagCalledDependencies'
import { FlagCalledArtifactType, flagCalledRebuildBannerLogic } from './flagCalledRebuildBannerLogic'

interface FlagCalledRebuildBannerProps {
    artifactType: FlagCalledArtifactType
    references: FlagCalledReferences
    action?: LemonBannerAction
    className?: string
    /** A function receives the resolved check, so a caller can list which of its parts depend on flag calls. */
    children: React.ReactNode | ((dependsOn: (references: FlagCalledReferences) => boolean) => React.ReactNode)
}

// Remove once every organization is on flag_evaluations_mode 2 and no saved artifact matches (#88126).
// Delete this folder, every component that renders it, and FEATURE_FLAGS.FLAG_CALLED_REBUILD_BANNERS together.
export function FlagCalledRebuildBanner({
    artifactType,
    references,
    action,
    className,
    children,
}: FlagCalledRebuildBannerProps): JSX.Element | null {
    const { bannersEnabled, referencedActions } = useValues(flagCalledRebuildBannerLogic)
    const { reportBannerShown, loadReferencedActions } = useActions(flagCalledRebuildBannerLogic)
    // Callers rebuild the references on every render, so the effect depends on this string instead of the array.
    const actionIdsKey = references.actionIds.join(',')

    useEffect(() => {
        if (bannersEnabled && actionIdsKey) {
            loadReferencedActions(actionIdsKey.split(',').map(Number))
        }
    }, [bannersEnabled, actionIdsKey, loadReferencedActions])

    const dependsOn = (candidate: FlagCalledReferences): boolean => dependsOnFlagCalls(candidate, referencedActions)
    const shown = bannersEnabled && dependsOn(references)

    useEffect(() => {
        if (shown) {
            reportBannerShown(artifactType)
        }
    }, [shown, artifactType, reportBannerShown])

    if (!shown) {
        return null
    }
    return (
        <LemonBanner type="warning" action={action} className={className}>
            {typeof children === 'function' ? children(dependsOn) : children}
        </LemonBanner>
    )
}
