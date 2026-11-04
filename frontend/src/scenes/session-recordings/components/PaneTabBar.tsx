import clsx from 'clsx'
import { Fragment, ReactNode } from 'react'

import { Separator, Tabs, TabsList, TabsTrigger } from '@posthog/quill'

export interface PaneTab<K extends string> {
    key: K
    label: ReactNode
    icon?: ReactNode
    dataAttr: string
    disabledReason?: string
    dividerBefore?: boolean
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
                    <Fragment key={tab.key}>
                        {tab.dividerBefore && <Separator orientation="vertical" className="h-4 self-center mx-1" />}
                        <TabsTrigger
                            value={tab.key}
                            disabled={!!tab.disabledReason}
                            className={clsx('text-xs', fullWidth ? 'flex-auto' : 'flex-none')}
                            data-attr={tab.dataAttr}
                        >
                            {tab.icon}
                            {tab.label}
                        </TabsTrigger>
                    </Fragment>
                ))}
                {!fullWidth && <div className="flex-1" />}
                {children}
            </TabsList>
        </Tabs>
    )
}
