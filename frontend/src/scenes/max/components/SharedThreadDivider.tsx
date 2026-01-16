import { IconLock } from '@posthog/icons'

export function SharedThreadDivider(): JSX.Element {
    return (
        <div className="flex items-center gap-2 py-3 text-xs text-muted">
            <div className="flex-1 border-t border-dashed border-border" />
            <div className="flex items-center gap-1.5 px-2">
                <IconLock className="text-muted" />
                <span>Messages beyond this point are only visible to you</span>
            </div>
            <div className="flex-1 border-t border-dashed border-border" />
        </div>
    )
}
