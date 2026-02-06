import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { healthMenuLogic } from '../HealthMenu/healthMenuLogic'

export function PosthogStatusShownOnlyIfNotOperational(): JSX.Element | null {
    const { postHogStatus, postHogStatusTooltip, postHogStatusBadgeStatus } = useValues(healthMenuLogic)

    if (postHogStatus === 'operational') {
        return null
    }

    const tooltipText = postHogStatusTooltip ?? 'PostHog status'
    const color = postHogStatusBadgeStatus === 'danger' ? 'var(--danger)' : 'var(--warning)'

    return (
        <div
            className="group"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ '--pulse-glow-color': color } as React.CSSProperties}
        >
            <Link
                buttonProps={{
                    iconOnly: true,
                    className: 'text-secondary group-hover:text-primary',
                }}
                to="https://posthogstatus.com"
                tooltip={tooltipText}
                tooltipCloseDelayMs={0}
                target="_blank"
            >
                <span className="relative flex size-4">
                    <span className="absolute inline-flex h-full w-full animate-pulse-glow rounded-full duration-1" />
                    <svg className="size-4" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path
                            d="M10 0C15.523 0 20 4.477 20 10C20 15.523 15.523 20 10 20C4.477 20 0 15.523 0 10C0 4.477 4.477 0 10 0ZM10 2C7.87827 2 5.84306 2.84248 4.34277 4.34277C2.84248 5.84306 2 7.87827 2 10C2 12.1217 2.84248 14.1569 4.34277 15.6572C5.84306 17.1575 7.87827 18 10 18C12.1217 18 14.1569 17.1575 15.6572 15.6572C17.1575 14.1569 18 12.1217 18 10C18 7.87827 17.1575 5.84306 15.6572 4.34277C14.1569 2.84248 12.1217 2 10 2ZM10 13C10.2652 13 10.5195 13.1054 10.707 13.293C10.8946 13.4805 11 13.7348 11 14C11 14.2652 10.8946 14.5195 10.707 14.707C10.5195 14.8946 10.2652 15 10 15C9.73478 15 9.48051 14.8946 9.29297 14.707C9.10543 14.5195 9 14.2652 9 14C9 13.7348 9.10543 13.4805 9.29297 13.293C9.48051 13.1054 9.73478 13 10 13ZM10 4.5C10.5523 4.5 11 4.94772 11 5.5V10.5C11 11.0523 10.5523 11.5 10 11.5C9.44772 11.5 9 11.0523 9 10.5V5.5C9 4.94772 9.44772 4.5 10 4.5Z"
                            fill="currentColor"
                        />
                    </svg>
                </span>
            </Link>
        </div>
    )
}
