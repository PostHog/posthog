import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { FlagCalledArtifactType, flagCalledRebuildBannerLogic } from './flagCalledRebuildBannerLogic'

interface FlagCalledRebuildBannerProps {
    artifactType: FlagCalledArtifactType
    children: React.ReactNode
}

// Remove once every organization is on flag_evaluations_mode 2 and no saved artifact matches (#88126).
// Delete this folder and every component that renders it together. Other move warnings read
// FEATURE_FLAGS.FLAG_CALLED_MOVE_NOTICES, so delete the flag only after they are gone too.
export function FlagCalledRebuildBanner({ artifactType, children }: FlagCalledRebuildBannerProps): JSX.Element | null {
    const { bannersEnabled, announcementUrl } = useValues(flagCalledRebuildBannerLogic)
    const { reportBannerShown } = useActions(flagCalledRebuildBannerLogic)

    useEffect(() => {
        if (bannersEnabled) {
            reportBannerShown(artifactType)
        }
    }, [bannersEnabled, artifactType, reportBannerShown])

    if (!bannersEnabled) {
        return null
    }
    return (
        <LemonBanner
            type="warning"
            action={announcementUrl ? { children: 'Learn more', to: announcementUrl, targetBlank: true } : undefined}
        >
            {children}
        </LemonBanner>
    )
}
