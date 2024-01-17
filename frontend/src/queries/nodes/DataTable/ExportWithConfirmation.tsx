import { Popconfirm } from 'antd'
import { Link } from 'lib/lemon-ui/Link'

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
            className="ant-popconfirm"
            placement={placement}
            title={
                <>
                    CSV export is limited to {limit} {actor}.
                    {actor === 'events' && (
                        <>
                            <br />
                            The best way to export events is to use{' '}
                            <Link to="https://posthog.com/apps?filter=type&value=data-out">our app ecosystem</Link>.
                        </>
                    )}
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
