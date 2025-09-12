import { useValues } from 'kea'
import posthog from 'posthog-js'
import React, { Fragment, useState } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonDivider, TooltipProps } from '@posthog/lemon-ui'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { Scene } from 'scenes/sceneTypes'

type SidebarChangeNoticeProps = {
    identifier: string | number
}

/**
 * Used in combination with a feature flag like:
 *
 * sidebar-notice-annotations-2023-10-30
 * matching:
 *   properties:
 *     sidebar_notice/annotations-2023-10-30: doesn't equal true
 *     joined_at: before 2023-10-30
 *
 */

const NOTICES: {
    identifier: Scene
    description: React.ReactNode
    placement: TooltipProps['placement']
    flagSuffix: string
}[] = [
    {
        identifier: Scene.DataManagement,
        description: (
            <>
                <b>Annotations</b> have moved here!
                <br />
                You can now find them in <b>Data Management</b>
            </>
        ),
        placement: 'bottom-end',
        flagSuffix: 'annotations-2023-10-30',
    },
    {
        identifier: Scene.Cohorts,
        description: (
            <>
                <b>Cohorts</b> have moved here!
                <br />
                You can now find them in <b>People</b>
            </>
        ),
        placement: 'top-end',
        flagSuffix: 'cohorts-2023-10-30',
    },
]

export function SidebarChangeNoticeContent({
    notices,
    onAcknowledged,
}: {
    notices: typeof NOTICES
    onAcknowledged: () => void
}): JSX.Element | null {
    return (
        <div className="flex items-center gap-1" onClick={onAcknowledged}>
            <div className="flex-1">
                {notices.map((notice, i) => (
                    <Fragment key={i}>
                        {notice.description}
                        {i < notices.length - 1 && <LemonDivider />}
                    </Fragment>
                ))}
            </div>

            <LemonButton size="small" onClick={onAcknowledged} icon={<IconX />} />
        </div>
    )
}

export function useSidebarChangeNotices({ identifier }: SidebarChangeNoticeProps): [typeof NOTICES, () => void] {
    const { featureFlags } = useValues(featureFlagLogic)
    const [noticeAcknowledged, setNoticeAcknowledged] = useState(false)

    const notices = NOTICES.filter((notice) => notice.identifier === identifier).filter(
        (notice) => featureFlags[`sidebar-notice-${notice.flagSuffix}`]
    )

    const onAcknowledged = (): void => {
        notices.forEach((change) => {
            posthog.capture('sidebar notice acknowledged', {
                change: change.flagSuffix,
                $set: {
                    [`sidebar_notice/${change.flagSuffix}`]: true,
                },
            })
            setNoticeAcknowledged(true)
        })
    }

    return [!noticeAcknowledged ? notices : [], onAcknowledged]
}
