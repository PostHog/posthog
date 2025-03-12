import { cn } from 'lib/utils/css-classes'

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
                className={cn(
                    'pl-1.5 pr-1 py-1 max-w-full',
                    'border-r',
                    'rounded-l rounded-r-none',
                    'overflow-hidden text-ellipsis',
                    type === 'success' ? 'bg-success-highlight' : 'bg-accent-primary-highlight'
                )}
            >
                <strong>
                    {title}
                    {titleSuffix}
                </strong>
            </span>
            <span
                className={cn(
                    'pr-1.5 pl-1 py-1 max-w-full',
                    'rounded-r rounded-l-none',
                    'overflow-hidden text-ellipsis',
                    type === 'success' ? 'bg-success-highlight' : 'bg-accent-primary-highlight',
                    'flex flex-1 items-center'
                )}
            >
                {value}
            </span>
        </div>
    )
}
