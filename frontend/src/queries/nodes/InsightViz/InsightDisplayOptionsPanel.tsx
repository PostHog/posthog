import { useState } from 'react'

import { LemonTabs } from 'lib/lemon-ui/LemonTabs'

import { SectionHeader } from './DisplayOptions'
import { DisplayOptionSection, DisplayOptionTab, DisplayOptionTabKey } from './insightDisplayOptions'

function DisplayOptionSectionList({ sections }: { sections: DisplayOptionSection[] }): JSX.Element {
    return (
        <ul>
            {sections.map((section) => (
                <li key={section.key}>
                    <section className="deprecated-space-y-px">
                        {section.title && (
                            <SectionHeader tooltip={section.tooltip} dataAttr={section.dataAttr}>
                                {section.title}
                            </SectionHeader>
                        )}
                        <ul className="deprecated-space-y-px" data-attr={section.title ? undefined : section.dataAttr}>
                            {section.items.map((Item, index) => (
                                <li key={index}>
                                    <Item />
                                </li>
                            ))}
                        </ul>
                    </section>
                </li>
            ))}
        </ul>
    )
}

export function InsightDisplayOptionsPanel({ tabs }: { tabs: DisplayOptionTab[] }): JSX.Element {
    const [activeKey, setActiveKey] = useState<DisplayOptionTabKey>(tabs[0]?.key ?? 'general')
    const activeTab = tabs.find((tab) => tab.key === activeKey) ?? tabs[0]

    if (tabs.length <= 1) {
        return (
            <div className="min-w-64 py-1" data-attr="insight-display-options-panel">
                {activeTab && <DisplayOptionSectionList sections={activeTab.sections} />}
            </div>
        )
    }

    return (
        <div className="min-w-64 py-1" data-attr="insight-display-options-panel">
            <LemonTabs
                size="small"
                activeKey={activeTab.key}
                onChange={setActiveKey}
                barClassName="mx-2 mb-1 overflow-x-visible [&>div]:w-full [&>div]:justify-around"
                data-attr="insight-display-options-tabs"
                tabs={tabs.map((tab) => ({
                    key: tab.key,
                    label: tab.label,
                    'data-attr': `insight-display-options-tab-${tab.key}`,
                    content: <DisplayOptionSectionList sections={tab.sections} />,
                }))}
            />
        </div>
    )
}
