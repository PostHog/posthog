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
        <div className={clsx('space-y-2 w-full h-full flex flex-col')}>
            {header}

            <div className={clsx('flex flex-col flex-1 space-y-2 h-full overflow-hidden overflow-y-scroll px-2')}>
                {body}
            </div>

            <div className={clsx('flex flex-row space-y-2 px-2 py-1')}>{footer}</div>
        </div>
    )
}
