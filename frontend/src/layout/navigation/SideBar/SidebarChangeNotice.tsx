import { LemonButton, LemonDivider, LemonDropdownProps, Popover } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import posthog from 'posthog-js'
import { Fragment, useState } from 'react'
import { Scene } from 'scenes/sceneTypes'

export type SidebarChangeNoticeProps = {
    identifier: string | number
    children: LemonDropdownProps['children']
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
            </>
        ),
        flagSuffix: 'annotations-2023-10-30',
    },
]

export function SidebarChangeNotice({ identifier, children }: SidebarChangeNoticeProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const [noticeAcknowledged, setNoticeAcknowledged] = useState(false)

    const notices = NOTICES.filter((notice) => notice.identifier === identifier).filter(
        (notice) => featureFlags[`sidebar-notice-${notice.flagSuffix}`]
    )

    if (noticeAcknowledged || !notices.length) {
        return children
    }

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

    return (
        <Popover
            placement="right-start"
            visible={true}
            showArrow
            overlay={
                <div className="max-w-50">
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
            }
        >
            {children}
        </Popover>
    )
}
