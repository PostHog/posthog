import clsx from 'clsx'
import { ReactNode } from 'react'

import { Tabs, TabsList, TabsTrigger } from '@posthog/quill'

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
        <Tabs
            data-quill
            value={activeKey}
            onValueChange={(value) => onChange(value as K)}
            className={clsx('shrink-0 gap-0', className)}
        >
            <TabsList variant="line" className="w-full justify-start rounded-none bg-muted">
                {tabs.map((tab) => (
                    <TabsTrigger
                        key={tab.key}
                        value={tab.key}
                        disabled={!!tab.disabledReason}
                        className={clsx('text-xs', fullWidth && 'flex-auto')}
                        data-attr={tab.dataAttr}
                    >
                        {tab.icon}
                        {tab.label}
                    </TabsTrigger>
                ))}
                {!fullWidth && <div className="flex-1" />}
                {children}
            </TabsList>
        </Tabs>
    )
}
