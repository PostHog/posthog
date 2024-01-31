import { IconExpand45 } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'
import clsx from 'clsx'
import React from 'react'

import { TileId } from './webAnalyticsLogic'

export const WebTabs = ({
    className,
    activeTabId,
    tabs,
    setActiveTabId,
    openModal,
    tileId,
}: {
    className?: string
    activeTabId: string
    tabs: { id: string; title: string; linkText: string; content: React.ReactNode; canOpenModal: boolean }[]
    setActiveTabId: (id: string) => void
    openModal: (tileId: TileId, tabId: string) => void
    tileId: TileId
}): JSX.Element => {
    const activeTab = tabs.find((t) => t.id === activeTabId)

    return (
        <div className={clsx(className, 'flex flex-col')}>
            <div className="flex flex-row items-center self-stretch mb-3">
                <h2 className="flex-1 m-0">{activeTab?.title}</h2>

                {tabs.length > 3 ? (
                    <LemonSelect
                        size="small"
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
            {activeTab?.canOpenModal ? (
                <div className="flex justify-end my-2">
                    <LemonButton
                        icon={<IconExpand45 />}
                        onClick={() => {
                            openModal(tileId, activeTabId)
                        }}
                        type="secondary"
                        size="small"
                    >
                        Expand
                    </LemonButton>
                </div>
            ) : null}
        </div>
    )
}
