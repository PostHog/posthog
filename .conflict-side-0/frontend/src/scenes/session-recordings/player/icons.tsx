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
                'flex justify-center items-center shrink-0 bg-muted-alt text-white rounded',
                size === 'medium' && 'w-5 h-5',
                size === 'small' && 'w-4 h-4',
                className
            )}
        >
            <span
                className={clsx(
                    'font-bold select-none',
                    size === 'medium' && 'text-xs',
                    size === 'small' && 'text-xxs'
                )}
            >
                {shortValue}
            </span>
        </div>
    )
}
