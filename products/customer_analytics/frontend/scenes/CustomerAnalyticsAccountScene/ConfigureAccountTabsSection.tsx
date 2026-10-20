import { DndContext } from '@dnd-kit/core'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'

import type { AccountTabDefinition } from './accountTabs'
import { ConfigureAccountTabsItem } from './ConfigureAccountTabsItem'

interface ConfigureAccountTabsSectionProps {
    title: string
    tabs: AccountTabDefinition[]
    disabledReason: string | undefined
    isTabVisible: (tab: AccountTabDefinition) => boolean
    onVisibilityChange: (tab: AccountTabDefinition, visible: boolean) => void
    onReorder: (activeTabId: string, overTabId: string) => void
}

export function ConfigureAccountTabsSection({
    title,
    tabs,
    disabledReason,
    isTabVisible,
    onVisibilityChange,
    onReorder,
}: ConfigureAccountTabsSectionProps): JSX.Element | null {
    if (tabs.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-2">
            <span className="font-medium">{title}</span>
            <DndContext
                onDragEnd={({ active, over }) => {
                    if (over) {
                        onReorder(String(active.id), String(over.id))
                    }
                }}
                modifiers={[restrictToVerticalAxis, restrictToParentElement]}
            >
                <SortableContext items={tabs.map((tab) => tab.id)} strategy={verticalListSortingStrategy}>
                    <div className="flex flex-col gap-2">
                        {tabs.map((tab) => (
                            <ConfigureAccountTabsItem
                                key={tab.id}
                                tab={tab}
                                visible={isTabVisible(tab)}
                                disabledReason={disabledReason}
                                onVisibilityChange={(visible) => onVisibilityChange(tab, visible)}
                            />
                        ))}
                    </div>
                </SortableContext>
            </DndContext>
        </div>
    )
}
