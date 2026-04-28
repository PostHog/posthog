import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { cn } from 'lib/utils/css-classes'
import { sceneLogic } from 'scenes/sceneLogic'
import { SceneConfig } from 'scenes/sceneTypes'

import { noEventsBannerLogic } from './noEventsBannerLogic'
import { projectNoticeLogic } from './projectNoticeLogic'

const LAYOUT_WITH_HORIZONTAL_MARGIN: SceneConfig['layout'][] = ['app-raw', 'app-raw-no-header']

export function ProjectNotice({ className }: { className?: string }): JSX.Element | null {
    const { projectNotice, projectNoticeVariant } = useValues(projectNoticeLogic)
    const { reportNoticeShown } = useActions(projectNoticeLogic)
    const { sceneConfig } = useValues(sceneLogic)

    const requiresHorizontalMargin = sceneConfig?.layout && LAYOUT_WITH_HORIZONTAL_MARGIN.includes(sceneConfig.layout)

    // KLUDGE: We can't really depend on `projectNotice` being set inside the logic
    // to trigger the action from inside the logic, so let's do it here.
    useEffect(() => {
        if (projectNoticeVariant) {
            reportNoticeShown()
        }
    }, [projectNoticeVariant, reportNoticeShown])

    if (!projectNotice) {
        return null
    }

    return (
        <>
            {projectNotice.mountNoEventsBannerLogic && <MountNoEventsBannerLogic />}
            <LemonBanner
                type={projectNotice.type || 'info'}
                className={cn('my-4', className, { 'mx-4': requiresHorizontalMargin })}
                action={projectNotice.action}
                onClose={projectNotice.onClose}
            >
                {projectNotice.message}
            </LemonBanner>
        </>
    )
}

/** Polls for ingested events while the "no events" banner is visible. */
function MountNoEventsBannerLogic(): null {
    useMountedLogic(noEventsBannerLogic)
    return null
}
