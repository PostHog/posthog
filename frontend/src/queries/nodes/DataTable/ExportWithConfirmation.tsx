import { Popconfirm } from 'antd'

interface ExportWithConfirmationProps {
    placement: 'topRight' | 'bottomRight'
    onConfirm: (e?: React.MouseEvent<HTMLElement>) => void
    actor: 'events' | 'persons'
    limit: number
    children: React.ReactNode
}

export function ExportWithConfirmation({
    placement,
    onConfirm,
    children,
    actor,
    limit,
}: ExportWithConfirmationProps): JSX.Element {
    return (
        <Popconfirm
            placement={placement}
            title={
                <>
                    Exporting by csv is limited to {limit} {actor}.
                    <br />
                    {actor === 'events' && (
                        <>
                            The best way to export is to use <a href="https://posthog.com/apps">our app ecosystem</a>.
                            <br />
                        </>
                    )}
                    For larger, infrequent exports you can use <a href="https://posthog.com/docs/api/events">the API</a>
                    .
                    <br />
                    Do you want to export by CSV?
                </>
            }
            onConfirm={onConfirm}
        >
            {children}
        </Popconfirm>
    )
}
