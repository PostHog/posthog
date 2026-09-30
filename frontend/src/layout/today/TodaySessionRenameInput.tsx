import { useActions } from 'kea'
import { useRef, useState } from 'react'

import { LemonInput } from '@posthog/lemon-ui'

import { todaySessionMenuLogic } from './todaySessionMenuLogic'

interface TodaySessionRenameInputProps {
    sessionId: string
    title: string
}

export function TodaySessionRenameInput({ sessionId, title }: TodaySessionRenameInputProps): JSX.Element {
    const [value, setValue] = useState(title)
    const finished = useRef(false)
    const { renameSession, stopRenaming } = useActions(todaySessionMenuLogic)

    const save = (): void => {
        if (finished.current) {
            return
        }
        finished.current = true
        const next = value.trim()
        if (next && next !== title) {
            renameSession(sessionId, next)
        } else {
            stopRenaming()
        }
    }

    return (
        <div className="TodayPaneRow">
            <LemonInput
                size="xsmall"
                fullWidth
                autoFocus
                value={value}
                onChange={setValue}
                onPressEnter={save}
                onBlur={save}
                onKeyDown={(event) => {
                    if (event.key === 'Escape') {
                        finished.current = true
                        stopRenaming()
                    }
                }}
                aria-label="Session title"
                data-attr="today-session-rename-input"
            />
        </div>
    )
}
