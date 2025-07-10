import clsx from 'clsx'

interface IconWindowProps {
    value: number | string
    size?: 'small' | 'medium'
    className?: string
}

export function IconWindow({ value, className = '', size = 'medium' }: IconWindowProps): JSX.Element {
    const shortValue = typeof value === 'number' ? value : String(value).charAt(0)

    return (
        <div
            className={clsx(
                'bg-muted-alt flex shrink-0 items-center justify-center rounded text-white',
                size === 'medium' && 'h-5 w-5',
                size === 'small' && 'h-4 w-4',
                className
            )}
        >
            <span
                className={clsx(
                    'select-none font-bold',
                    size === 'medium' && 'text-xs',
                    size === 'small' && 'text-xxs'
                )}
            >
                {shortValue}
            </span>
        </div>
    )
}
