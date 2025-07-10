import clsx from 'clsx'

export function TitledSnack({
    title,
    value,
    type = 'default',
    titleSuffix = ':',
}: {
    title: string
    titleSuffix?: string
    value: string | JSX.Element
    type?: 'default' | 'success'
}): JSX.Element {
    return (
        <div className="flex flex-row items-center">
            <span
                className={clsx(
                    'max-w-full py-1 pl-1.5 pr-1',
                    'border-r',
                    'rounded-l rounded-r-none',
                    'overflow-hidden text-ellipsis',
                    type === 'success' ? 'bg-success-highlight' : 'bg-accent-highlight-secondary'
                )}
            >
                <strong>
                    {title}
                    {titleSuffix}
                </strong>
            </span>
            <span
                className={clsx(
                    'max-w-full py-1 pl-1 pr-1.5',
                    'rounded-l-none rounded-r',
                    'overflow-hidden text-ellipsis',
                    type === 'success' ? 'bg-success-highlight' : 'bg-accent-highlight-secondary',
                    'flex flex-1 items-center'
                )}
            >
                {value}
            </span>
        </div>
    )
}
