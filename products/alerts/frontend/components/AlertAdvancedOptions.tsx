import { ReactNode } from 'react'

import { LemonCollapse } from '@posthog/lemon-ui'

interface AlertAdvancedOptionsProps {
    children: ReactNode
    enabledCount?: number
}

export function AlertAdvancedOptions({ children, enabledCount = 0 }: AlertAdvancedOptionsProps): JSX.Element {
    const countLabel = `${enabledCount} advanced option${enabledCount === 1 ? '' : 's'} on`

    return (
        <LemonCollapse
            panels={[
                {
                    key: 'advanced',
                    header: {
                        type: enabledCount > 0 ? 'primary' : 'tertiary',
                        children: (
                            <span className="flex w-full min-w-0 items-center justify-between gap-2">
                                <span className="min-w-0">Advanced options</span>
                                {enabledCount > 0 ? (
                                    <span
                                        className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-current/20 bg-current/10 text-xs font-semibold tabular-nums leading-none"
                                        aria-label={countLabel}
                                    >
                                        {enabledCount}
                                    </span>
                                ) : null}
                            </span>
                        ),
                    },
                    content: <div className="space-y-2">{children}</div>,
                },
            ]}
        />
    )
}
