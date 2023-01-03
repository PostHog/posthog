import clsx from 'clsx'

export function IconWindow({ value, className = '' }: { value: number | string; className?: string }): JSX.Element {
    const shortValue = typeof value === 'number' ? value : String(value).charAt(0)
    return (
        <div className={clsx('flex justify-center items-center relative shrink-0', className)}>
            <span className="absolute font-semibold" style={{ fontSize: 8, marginTop: 2 }}>
                {shortValue}
            </span>
            <svg
                className="text-lg"
                width="24"
                height="24"
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
