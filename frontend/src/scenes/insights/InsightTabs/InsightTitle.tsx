import React, { RefObject, useMemo, useRef, useState } from 'react'
import { DashboardOutlined, DownOutlined } from '@ant-design/icons'
import { router } from 'kea-router'
import { useValues } from 'kea'
import { insightHistoryLogic } from '../InsightHistoryPanel/insightHistoryLogic'
import { SelectBox, SelectedItem } from 'lib/components/SelectBox'
import './InsightTitle.scss'
import { ViewType } from '../insightLogic'
import { capitalizeFirstLetter } from 'lib/utils'

export function InsightTitle({ actionBar = null }: { actionBar?: JSX.Element | null }): JSX.Element {
    const [savedInsightsOpen, setSavedInsightsOpen] = useState(false)
    const [{ fromItemName, fromDashboard }] = useState(router.values.hashParams)
    const buttonRef = useRef<HTMLDivElement>(null)

    return (
        <div className="insight-title">
            <div className="flex-contain">
                <div
                    className="flex-contain"
                    style={{ cursor: 'pointer' }}
                    onClick={() => setSavedInsightsOpen(!savedInsightsOpen)}
                    ref={buttonRef}
                >
                    {fromDashboard && (
                        <DashboardOutlined
                            style={{ color: 'var(--warning)', marginRight: 4 }}
                            title="Insight saved on dashboard"
                        />
                    )}
                    <h3 className="l3" style={{ marginBottom: 0 }}>
                        {fromItemName || 'Unsaved query'}
                    </h3>
                    <DownOutlined style={{ marginLeft: 4 }} />
                </div>
                {actionBar}
            </div>
            {
                <SavedInsightsDropdown
                    open={savedInsightsOpen}
                    onClose={() => setSavedInsightsOpen(false)}
                    openButtonRef={buttonRef}
                />
            }
        </div>
    )
}

function SavedInsightsDropdown({
    open,
    openButtonRef,
    onClose,
}: {
    open: boolean
    openButtonRef: RefObject<HTMLElement>
    onClose: () => void
}): JSX.Element | null {
    const { savedInsights } = useValues(insightHistoryLogic)

    const items = useMemo(
        () =>
            Object.keys(ViewType).map((view) => ({
                key: view,
                name: `Saved ${capitalizeFirstLetter(view.toLowerCase())}`,
                header: function header(label: string) {
                    return <>{label}</>
                },
                dataSource: savedInsights.reduce((accumulator, item) => {
                    if (item.filters.insight === view) {
                        accumulator.push({
                            id: item.id,
                            value: item.name,
                            key: item.id.toString(),
                            name: item.name,
                            groupName: view,
                        })
                    }
                    return accumulator
                }, [] as SelectedItem[]),
                type: view,
                getValue: (item: SelectedItem) => item.key || '',
                getLabel: (item: SelectedItem) => item.name || '',
            })),
        [savedInsights]
    )

    const handleDismiss = (event?: MouseEvent): void => {
        if (openButtonRef?.current?.contains(event?.target as Node)) {
            return
        }
        onClose()
    }

    if (!open) {
        return null
    }

    return (
        <SelectBox
            items={items}
            onSelect={(type, id, name) => console.log(type, id, name)}
            onDismiss={handleDismiss}
            disablePopover
            disableInfoBox
            inputPlaceholder="Navigate to saved insights..."
        />
    )
}
