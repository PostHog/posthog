import clsx from 'clsx'
import { ReactNode } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

export interface PaneTab<K extends string> {
    key: K
    label: ReactNode
    icon?: ReactNode
    dataAttr: string
    disabledReason?: string
}

export function PaneTabBar<K extends string>({
    tabs,
    activeKey,
    onChange,
    fullWidth = false,
    className,
    children,
}: {
    tabs: PaneTab<K>[]
    activeKey: K
    onChange: (key: K) => void
    fullWidth?: boolean
    className?: string
    children?: ReactNode
}): JSX.Element {
    return (
        <div className={clsx('flex flex-row items-stretch shrink-0 border-b bg-surface-secondary', className)}>
            {tabs.map((tab) => {
                const active = activeKey === tab.key
                return (
                    <LemonButton
                        key={tab.key}
                        noPadding
                        active={active}
                        onClick={() => onChange(tab.key)}
                        disabledReason={tab.disabledReason}
                        className={clsx(
                            'rounded-none border-b-2',
                            active ? 'border-b-accent bg-surface-primary' : 'border-b-transparent',
                            fullWidth && 'flex-auto'
                        )}
                        data-attr={tab.dataAttr}
                    >
                        <span
                            className={clsx(
                                'flex items-center gap-1.5 px-3 py-1.5 text-xs',
                                fullWidth && 'justify-center w-full'
                            )}
                        >
                            {tab.icon && <span className="text-base">{tab.icon}</span>}
                            <span className="flex items-center gap-1">{tab.label}</span>
                        </span>
                    </LemonButton>
                )
            })}
            {!fullWidth && <div className="flex-1" />}
            {children}
        </div>
    )
}
