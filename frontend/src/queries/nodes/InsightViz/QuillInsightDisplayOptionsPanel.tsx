import { useState } from 'react'

import { FieldLegend, FieldSet, Tabs, TabsContent, TabsList, TabsTrigger } from '@posthog/quill'

import { DisplayOptionSection, DisplayOptionTab, DisplayOptionTabKey } from './insightDisplayOptions'
import { QuillDisplayOptionInfo } from './QuillDisplayOptionInfo'

function SectionList({ sections }: { sections: DisplayOptionSection[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            {sections.map((section) => (
                <FieldSet key={section.key} className="gap-2">
                    {section.title && (
                        <FieldLegend variant="label" className="flex items-center gap-1" data-attr={section.dataAttr}>
                            {section.title}
                            {section.tooltip && <QuillDisplayOptionInfo info={section.tooltip} />}
                        </FieldLegend>
                    )}
                    <div className="flex flex-col gap-2" data-attr={section.title ? undefined : section.dataAttr}>
                        {section.items.map((Item, index) => (
                            <Item key={index} />
                        ))}
                    </div>
                </FieldSet>
            ))}
        </div>
    )
}

export function QuillInsightDisplayOptionsPanel({ tabs }: { tabs: DisplayOptionTab[] }): JSX.Element | null {
    const [activeKey, setActiveKey] = useState<DisplayOptionTabKey>(tabs[0]?.key ?? 'general')
    const activeTab = tabs.find((tab) => tab.key === activeKey) ?? tabs[0]

    if (!activeTab) {
        return null
    }

    if (tabs.length === 1) {
        return (
            <div data-attr="insight-display-options-panel">
                <SectionList sections={activeTab.sections} />
            </div>
        )
    }

    return (
        <Tabs
            value={activeTab.key}
            onValueChange={(key) => setActiveKey(key as DisplayOptionTabKey)}
            className="gap-3 [--quill-tabs-active-bg:var(--card)]"
            data-attr="insight-display-options-panel"
        >
            <TabsList variant="line" className="w-full" data-attr="insight-display-options-tabs">
                {tabs.map((tab) => (
                    <TabsTrigger key={tab.key} value={tab.key} data-attr={`insight-display-options-tab-${tab.key}`}>
                        {tab.label}
                    </TabsTrigger>
                ))}
            </TabsList>
            {tabs.map((tab) => (
                <TabsContent key={tab.key} value={tab.key}>
                    <SectionList sections={tab.sections} />
                </TabsContent>
            ))}
        </Tabs>
    )
}
