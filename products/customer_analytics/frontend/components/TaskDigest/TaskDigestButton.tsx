import posthog from 'posthog-js'
import { useState } from 'react'

import { IconBell } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { AccountsEvents } from '../Accounts/constants'
import { QuillTaskDigestButton } from './QuillTaskDigestButton'
import { TaskDigestModal } from './TaskDigestModal'

export function TaskDigestButton(): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return <QuillTaskDigestButton />
    }

    return (
        <>
            <LemonButton
                type="tertiary"
                size="small"
                icon={<IconBell fontSize="16" />}
                data-attr="customer-analytics-email-digest"
                onClick={() => {
                    posthog.capture(AccountsEvents.TaskDigestOpened, { source: 'tasks' })
                    setIsOpen(true)
                }}
            >
                Email digest
            </LemonButton>
            {isOpen && <TaskDigestModal onClose={() => setIsOpen(false)} />}
        </>
    )
}
