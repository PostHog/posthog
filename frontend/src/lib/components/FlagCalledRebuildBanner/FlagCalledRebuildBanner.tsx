import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonBannerAction } from 'lib/lemon-ui/LemonBanner/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'

import { FlagCalledArtifactType, flagCalledRebuildBannerLogic } from './flagCalledRebuildBannerLogic'

interface FlagCalledRebuildBannerProps {
    artifactType: FlagCalledArtifactType
    readsFlagCalls: boolean
    action?: LemonBannerAction
    className?: string
    children: React.ReactNode
}

// Remove once every organization is on flag_evaluations_mode 2 and no saved artifact matches (#88126).
// Delete this folder and every component that renders it together. Other move warnings read
// FEATURE_FLAGS.FLAG_CALLED_MOVE_NOTICES, so delete the flag only after they are gone too.
export function FlagCalledRebuildBanner({
    artifactType,
    readsFlagCalls,
    action,
    className,
    children,
}: FlagCalledRebuildBannerProps): JSX.Element | null {
    const { bannersEnabled, announcementUrl } = useValues(flagCalledRebuildBannerLogic)
    const { reportBannerShown } = useActions(flagCalledRebuildBannerLogic)
    const shown = bannersEnabled && readsFlagCalls

    useEffect(() => {
        if (shown) {
            reportBannerShown(artifactType)
        }
    }, [shown, artifactType, reportBannerShown])

    if (!shown) {
        return null
    }
    const announcementAction: LemonBannerAction | undefined = announcementUrl
        ? { children: 'Learn more', to: announcementUrl, targetBlank: true }
        : undefined
    return (
        <LemonBanner type="warning" action={action ?? announcementAction} className={className}>
            {children}
            {/* A banner that already has a button links the announcement at the end of its text instead. */}
            {action && announcementUrl && (
                <>
                    {' '}
                    <Link to={announcementUrl} target="_blank">
                        Learn more
                    </Link>
                </>
            )}
        </LemonBanner>
    )
}
