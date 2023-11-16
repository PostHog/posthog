import clsx from 'clsx'

export function ToolbarMenu({
    header,
    body,
    footer,
}: {
    header: JSX.Element | null
    body: JSX.Element | null
    footer: JSX.Element | null
}): JSX.Element {
    return (
        <div className={clsx('space-y-2 w-full h-full flex flex-col overflow-hidden')}>
            {header}
            <div className={clsx('flex flex-col flex-1 h-full overflow-hidden overflow-y-auto')}>{body}</div>
            <div className={clsx('flex flex-row')}>{footer}</div>
        </div>
    )
}
