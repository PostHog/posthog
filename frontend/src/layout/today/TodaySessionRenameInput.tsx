import { useActions } from 'kea'
import { ChangeEvent, KeyboardEvent, useRef, useState } from 'react'

import { Input } from '@posthog/quill'

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
        <Input
            autoFocus
            value={value}
            onChange={(event: ChangeEvent<HTMLInputElement>) => setValue(event.target.value)}
            onBlur={save}
            onKeyDown={(event: KeyboardEvent<HTMLInputElement>) => {
                if (event.key === 'Enter') {
                    save()
                } else if (event.key === 'Escape') {
                    finished.current = true
                    stopRenaming()
                }
            }}
            aria-label="Session title"
            data-attr="today-session-rename-input"
        />
    )
}
