import { LemonButton, LemonDivider, Tooltip, TooltipProps } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import posthog from 'posthog-js'
import React, { Fragment, useState } from 'react'
import { Scene } from 'scenes/sceneTypes'

export type SidebarChangeNoticeProps = {
    identifier: string | number
}

export type SidebarChangeNoticeTooltipProps = SidebarChangeNoticeProps & {
    children: TooltipProps['children']
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
    flagSuffix: string
}[] = [
    {
        identifier: Scene.DataManagement,
        description: (
            <>
                <b>Annotations</b> have moved! You can now find them in the <b>Data Management</b> section.
                <br />
                <br />
                <b>Cohorts</b> have moved! You can now find them in the <b>People & Groups</b> section.
            </>
        ),
        flagSuffix: 'annotations-2023-10-30',
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
        <div className="max-w-80">
            {notices.map((notice, i) => (
                <Fragment key={i}>
                    {notice.description}
                    <LemonDivider />
                </Fragment>
            ))}

            <div className="flex justify-end">
                <LemonButton type="primary" onClick={onAcknowledged}>
                    Understood!
                </LemonButton>
            </div>
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

export function SidebarChangeNoticeTooltip({
    identifier,
    children,
}: SidebarChangeNoticeTooltipProps): React.ReactNode | null {
    const [notices, onAcknowledged] = useSidebarChangeNotices({ identifier })

    if (!notices.length) {
        return children
    }

    return (
        <Tooltip
            visible={true}
            placement="right"
            overlay={<SidebarChangeNoticeContent notices={notices} onAcknowledged={onAcknowledged} />}
        >
            {children}
        </Tooltip>
    )
}
