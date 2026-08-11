import { IconMessage } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

export function ConversationsWidgetPreview(): JSX.Element {
    return (
        <div className="flex flex-col divide-y divide-border shadow-sm">
            {['Unable to finish checkout', 'Question about billing', 'Login link expired'].map((title, index) => (
                <div key={title} className="flex items-center gap-2 px-3 py-2">
                    <IconMessage className="size-4 text-muted" />
                    <span className="text-xs text-muted">#{124 - index}</span>
                    <span className="min-w-0 flex-1 truncate font-semibold">{title}</span>
                    <LemonTag type="muted">{index === 2 ? 'resolved' : 'open'}</LemonTag>
                </div>
            ))}
        </div>
    )
}
