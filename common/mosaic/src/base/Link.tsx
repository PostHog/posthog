import type { ReactElement, ReactNode } from 'react'

import { cn } from '../utils'

const ExternalIcon = (): ReactElement => (
    <svg
        width="1em"
        height="1em"
        viewBox="0 0 16 16"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="inline-block shrink-0"
    >
        <path
            d="M6 3H3.5A1.5 1.5 0 0 0 2 4.5v8A1.5 1.5 0 0 0 3.5 14h8a1.5 1.5 0 0 0 1.5-1.5V10m-4-7h4m0 0v4m0-4L7.5 8.5"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
        />
    </svg>
)

export interface LinkProps {
    href: string
    children: ReactNode
    external?: boolean
    onClick?: (e: React.MouseEvent<HTMLAnchorElement>) => void
    className?: string
}

export function Link({ href, children, external, onClick, className }: LinkProps): ReactElement {
    return (
        <a
            href={href}
            onClick={onClick}
            target={external ? '_blank' : undefined}
            rel={external ? 'noopener noreferrer' : undefined}
            className={cn(
                'inline-flex items-center gap-1 text-text-secondary hover:text-text-primary transition-colors cursor-pointer no-underline',
                className
            )}
        >
            {children}
            {external && <ExternalIcon />}
        </a>
    )
}
