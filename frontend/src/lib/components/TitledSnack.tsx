import clsx from 'clsx'

export function TitledSnack({
    title,
    value,
    type = 'default',
}: {
    title: string
    value: string | JSX.Element
    type?: 'default' | 'success'
}): JSX.Element {
    return (
        <div className="flex flex-row items-center">
            <span
                className={clsx(
                    'pl-1.5 pr-1 py-1 max-w-full',
                    'border-r',
                    'rounded-l rounded-r-none',
                    'text-primary-alt overflow-hidden text-ellipsis',
                    type === 'success' ? 'bg-success-highlight' : 'bg-primary-highlight'
                )}
            >
                <strong>{title}:</strong>
            </span>
            <span
                className={clsx(
                    'pr-1.5 pl-1 py-1 max-w-full',
                    'rounded-r rounded-l-none',
                    'text-primary-alt overflow-hidden text-ellipsis',
                    type === 'success' ? 'bg-success-highlight' : 'bg-primary-highlight',
                    'flex flex-1 items-center'
                )}
            >
                {value}
            </span>
        </div>
    )
}
