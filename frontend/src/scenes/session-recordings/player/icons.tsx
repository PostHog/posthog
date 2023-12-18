import clsx from 'clsx'

interface IconWindowProps {
    value: number | string
    size?: 'small' | 'medium'
    className?: string
}

export function IconWindowOld({ value, className = '', size = 'medium' }: IconWindowProps): JSX.Element {
    const shortValue = typeof value === 'number' ? value : String(value).charAt(0)
    return (
        <div className={clsx('flex justify-center items-center relative shrink-0', className)}>
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <span className="absolute font-semibold mt-0.5" style={{ fontSize: size === 'medium' ? 8 : 6 }}>
                {shortValue}
            </span>
            <svg
                className="text-lg"
                width={size === 'medium' ? 24 : 20}
                height={size === 'medium' ? 24 : 20}
                viewBox="0 0 24 24"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
            >
                <path
                    d="M19 4H5C3.89 4 3 4.9 3 6V18C3 19.1 3.89 20 5 20H19C20.1 20 21 19.1 21 18V6C21 4.9 20.11 4 19 4ZM19 18H5V8H19V18Z"
                    fill="currentColor"
                />
            </svg>
        </div>
    )
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
