import posthog from 'posthog-js'
import { useState } from 'react'

import { IconBell } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { AccountsEvents } from '../Accounts/constants'
import { TaskDigestModal } from './TaskDigestModal'

export function QuillTaskDigestButton(): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)

    return (
        <>
            <Button
                data-attr="customer-analytics-email-digest"
                onClick={() => {
                    posthog.capture(AccountsEvents.TaskDigestOpened, { source: 'tasks' })
                    setIsOpen(true)
                }}
            >
                <IconBell />
                Email digest
            </Button>
            {isOpen && <TaskDigestModal onClose={() => setIsOpen(false)} />}
        </>
    )
}
