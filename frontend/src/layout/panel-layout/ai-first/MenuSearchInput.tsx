import { useEffect, useRef } from 'react'

/**
 * Search input for menu popups. Uses a delayed focus instead of autoFocus
 * so focus works reliably inside portaled Menu popups.
 */
export function MenuSearchInput({ onKeyDown, ...props }: React.InputHTMLAttributes<HTMLInputElement>): JSX.Element {
    const ref = useRef<HTMLInputElement>(null)

    useEffect(() => {
        const timer = setTimeout(() => ref.current?.focus(), 0)
        return () => clearTimeout(timer)
    }, [])

    return (
        <input
            ref={ref}
            type="text"
            onKeyDown={(e) => {
                if (e.key !== 'Escape' && e.key !== 'Tab') {
                    e.stopPropagation()
                }
                onKeyDown?.(e)
            }}
            className="w-full px-2 py-1.5 text-sm rounded-sm border border-primary bg-surface-primary focus:outline-none focus:ring-1 focus:ring-primary mb-1"
            {...props}
        />
    )
}
