import { useState } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { Button, Input } from '@posthog/quill'

export function SectionTitle({
    title,
    collapsed,
    canEdit,
    onToggle,
    onRename,
}: {
    title: string
    collapsed: boolean
    canEdit: boolean
    onToggle: () => void
    onRename: (title: string) => void
}): JSX.Element {
    const [draft, setDraft] = useState<string | null>(null)

    const commit = (): void => {
        if (draft !== null && draft.trim() && draft !== title) {
            onRename(draft.trim())
        }
        setDraft(null)
    }

    let label: JSX.Element
    if (draft !== null) {
        label = (
            <Input
                autoFocus
                className="h-6 w-56 text-sm font-semibold"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onBlur={commit}
                onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                        commit()
                    } else if (event.key === 'Escape') {
                        setDraft(null)
                    }
                }}
            />
        )
    } else if (canEdit) {
        label = (
            <Button
                size="xs"
                className="text-sm font-semibold"
                tooltip="Rename"
                data-attr="dashboard-v2-section-rename"
                onClick={() => setDraft(title)}
            >
                {title}
            </Button>
        )
    } else {
        label = <span className="text-sm font-semibold truncate">{title}</span>
    }

    return (
        <div className="flex items-center gap-1 min-w-0">
            <Button
                size="icon-xs"
                aria-label={collapsed ? 'Expand' : 'Collapse'}
                aria-expanded={!collapsed}
                data-attr="dashboard-v2-section-toggle"
                disabledReason={canEdit ? undefined : 'Unlock the layout to open or close sections'}
                onClick={onToggle}
            >
                {collapsed ? <IconChevronRight /> : <IconChevronDown />}
            </Button>
            {label}
        </div>
    )
}
