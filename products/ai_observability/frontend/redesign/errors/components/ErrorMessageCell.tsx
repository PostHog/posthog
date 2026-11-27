import { Tooltip } from '@posthog/lemon-ui'

export interface ErrorMessageCellProps {
    message: string
    onOpen: () => void
}

// The message is the customer's own error text, so neither the cell nor its tooltip may reach session replay or
// autocapture. The message is the button that opens the error, so a keyboard reaches what a row click opens, and the
// button keeps the table cell's type style.
export function ErrorMessageCell({ message, onOpen }: ErrorMessageCellProps): JSX.Element {
    return (
        <Tooltip
            title={<span className="ph-no-capture whitespace-pre-wrap break-words font-mono text-xs">{message}</span>}
            placement="bottom-start"
        >
            <button
                type="button"
                onClick={(event) => {
                    event.stopPropagation()
                    onOpen()
                }}
                className="ph-no-capture block cursor-pointer border-0 bg-transparent p-0 text-left text-inherit hover:text-primary"
            >
                <span className="line-clamp-2 min-w-60 max-w-120 break-words font-mono text-xs">{message}</span>
            </button>
        </Tooltip>
    )
}
