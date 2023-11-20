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
        <div className={clsx('w-full h-full flex flex-col overflow-hidden')}>
            {header ? <div className="pt-1 px-1">{header}</div> : null}
            <div className={clsx('flex flex-col flex-1 h-full overflow-hidden overflow-y-auto px-2')}>{body}</div>
            {footer ? <div className={clsx('flex flex-row p-2')}>{footer}</div> : null}
        </div>
    )
}
