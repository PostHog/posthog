import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonBannerAction } from 'lib/lemon-ui/LemonBanner/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'

import { FlagCalledReferences, dependsOnFlagCalls } from './flagCalledDependencies'
import { FlagCalledArtifactType, flagCalledRebuildBannerLogic } from './flagCalledRebuildBannerLogic'

interface FlagCalledRebuildBannerProps {
    artifactType: FlagCalledArtifactType
    references: FlagCalledReferences
    action?: LemonBannerAction
    className?: string
    /** A function child receives `dependsOn`, which reports whether a set of references reads flag calls, directly or through a loaded action. */
    children: React.ReactNode | ((dependsOn: (references: FlagCalledReferences) => boolean) => React.ReactNode)
}

// Remove once every organization is on flag_evaluations_mode 2 and no saved artifact matches (#88126).
// Delete this folder and every component that renders it together. Other move warnings read
// FEATURE_FLAGS.FLAG_CALLED_MOVE_NOTICES, so delete the flag only after they are gone too.
export function FlagCalledRebuildBanner({
    artifactType,
    references,
    action,
    className,
    children,
}: FlagCalledRebuildBannerProps): JSX.Element | null {
    const { bannersEnabled, referencedActions, announcementUrl } = useValues(flagCalledRebuildBannerLogic)
    const { reportBannerShown, loadReferencedActions } = useActions(flagCalledRebuildBannerLogic)
    // Callers rebuild the references on every render, so the effect depends on this string instead of the array.
    const actionIdsKey = references.actionIds.join(',')
    // Dashboard tiles stream in, so the referenced ids grow across renders. Each id is requested once per mount.
    const requestedIdsRef = useRef(new Set<number>())

    useEffect(() => {
        if (!bannersEnabled || !actionIdsKey) {
            return
        }
        const unrequestedIds = [...new Set(actionIdsKey.split(',').map(Number))].filter(
            (id) => !requestedIdsRef.current.has(id)
        )
        if (unrequestedIds.length) {
            loadReferencedActions(unrequestedIds)
            unrequestedIds.forEach((id) => requestedIdsRef.current.add(id))
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
    const announcementAction: LemonBannerAction | undefined = announcementUrl
        ? { children: 'Read the announcement', to: announcementUrl, targetBlank: true }
        : undefined
    return (
        <LemonBanner type="warning" action={action ?? announcementAction} className={className}>
            {typeof children === 'function' ? children(dependsOn) : children}
            {/* A banner that already has a button shows the announcement as a link at the end of its text. */}
            {action && announcementUrl && (
                <>
                    {' '}
                    <Link to={announcementUrl} target="_blank">
                        Read the announcement
                    </Link>
                </>
            )}
        </LemonBanner>
    )
}
