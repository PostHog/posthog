import { LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'
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
                {tabs.length > 3 ? (
                    <LemonSelect
                        size={'small'}
                        disabled={false}
                        value={activeTabId}
                        dropdownMatchSelectWidth={false}
                        onChange={setActiveTabId}
                        options={tabs.map(({ id, linkText }) => ({ value: id, label: linkText }))}
                    />
                ) : (
                    <LemonSegmentedButton
                        size="small"
                        options={tabs.map(({ id, linkText }) => ({ label: linkText, value: id }))}
                        onChange={(value) => setActiveTabId(value)}
                        value={activeTabId}
                    />
                )}
            </div>
            <div className="flex-1 flex flex-col">{activeTab?.content}</div>
        </div>
    )
}
