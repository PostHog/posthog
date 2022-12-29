import { Popconfirm } from 'antd'
import { Link } from 'lib/components/Link'

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
                    For larger, ad-hoc exports you can use{' '}
                    <Link to={`https://posthog.com/docs/api/${actor}`}>the API</Link>.
                    {actor === 'events' && (
                        <>
                            <br />
                            The best way to export events is to use{' '}
                            <Link to="https://posthog.com/apps">our app ecosystem</Link>.
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
