import { IconCopy } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

export interface TraceCopyButtonProps {
    loading: boolean
    onCopy: () => void
    disabledReason?: string
}

export function TraceCopyButton({ loading, onCopy, disabledReason }: TraceCopyButtonProps): JSX.Element {
    return (
        <LemonButton
            size="small"
            type="secondary"
            icon={<IconCopy />}
            loading={loading}
            onClick={onCopy}
            disabledReason={disabledReason}
            tooltip="Copy this trace as JSON"
            data-attr="trace-view-copy"
        />
    )
}
