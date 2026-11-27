import { Tooltip } from '@posthog/lemon-ui'

export interface ErrorMessageCellProps {
    message: string
}

// The message is the customer's own error text, so neither the cell nor its tooltip may reach session replay or
// autocapture.
export function ErrorMessageCell({ message }: ErrorMessageCellProps): JSX.Element {
    return (
        <Tooltip
            title={<span className="ph-no-capture whitespace-pre-wrap break-words font-mono text-xs">{message}</span>}
            placement="bottom-start"
        >
            <div className="ph-no-capture line-clamp-2 min-w-60 max-w-120 break-words font-mono text-xs">{message}</div>
        </Tooltip>
    )
}
