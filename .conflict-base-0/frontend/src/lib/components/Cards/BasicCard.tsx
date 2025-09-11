import { useValues } from 'kea'
import { router } from 'kea-router'

import { useAnchor } from 'lib/hooks/useAnchor'
import { cn } from 'lib/utils/css-classes'

interface BasicCardProps extends React.HTMLAttributes<HTMLDivElement> {
    children: React.ReactNode
    backgroundColor?: string
}

export function BasicCard({ children, className, id, backgroundColor, ...props }: BasicCardProps): JSX.Element {
    // If the card ID is in the URL, we want to highlight it and scroll to it
    const { location } = useValues(router)
    useAnchor(location.hash)

    return (
        <div
            className={cn('border border-primary rounded flex flex-col p-3', className)}
            // eslint-disable-next-line react/forbid-dom-props
            style={
                {
                    // We use this value in the animation 'animate-mark' so it can return to it's original color
                    '--original-bg': backgroundColor || 'var(--color-bg-surface-primary)',
                    backgroundColor: 'var(--original-bg)',
                } as React.CSSProperties
            }
            id={id}
            {...props}
        >
            {children}
        </div>
    )
}
