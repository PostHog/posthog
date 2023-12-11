import { LemonTabs } from '@posthog/lemon-ui'
import clsx from 'clsx'
import React from 'react'

export const WebTabs = ({
    className,
    activeTabId,
    tabs,
    setActiveTabId,
}: {
    className?: string
    activeTabId: string
    tabs: { id: string; title: string; linkText: string; content: React.ReactNode }[]
    setActiveTabId: (id: string) => void
}): JSX.Element => {
    const activeTab = tabs.find((t) => t.id === activeTabId)

    return (
        <div className={clsx(className, 'flex flex-col')}>
            <div className="flex flex-row items-center self-stretch mb-3">
                {<h2 className="flex-1 m-0">{activeTab?.title}</h2>}
                <LemonTabs
                    inline
                    borderless
                    activeKey={activeTabId}
                    onChange={setActiveTabId}
                    tabs={tabs.map(({ id, linkText }) => ({ key: id, label: linkText }))}
                />
            </div>
            <div className="flex-1 flex flex-col">{activeTab?.content}</div>
        </div>
    )
}
