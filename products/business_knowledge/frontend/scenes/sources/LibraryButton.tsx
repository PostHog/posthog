import { IconFolder, IconFolderOpen } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import type { KnowledgeLibrary } from '../../api'

export function LibraryButton({
    library,
    active,
    onClick,
}: {
    library: KnowledgeLibrary
    active: boolean
    onClick: () => void
}): JSX.Element {
    return (
        <LemonButton
            size="small"
            icon={active ? <IconFolderOpen /> : <IconFolder />}
            active={active}
            onClick={onClick}
            data-attr="business-knowledge-library-select"
        >
            <span className="max-w-40 truncate">{library.name}</span>
            <span className="ml-1.5 text-xs text-secondary">{library.source_count}</span>
        </LemonButton>
    )
}
