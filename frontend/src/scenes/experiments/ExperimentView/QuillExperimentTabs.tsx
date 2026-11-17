import { Badge, Tabs, TabsList, TabsTrigger } from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

import { type ExperimentTab } from '../experimentSceneLogic'

export interface ExperimentTabDefinition {
    key: ExperimentTab
    label: string
    content: JSX.Element
    count?: number
}

export function QuillExperimentTabs({
    tabs,
    activeKey,
    onChange,
    badgeVariant,
}: {
    tabs: ExperimentTabDefinition[]
    activeKey: ExperimentTab
    onChange: (key: ExperimentTab) => void
    badgeVariant: 'destructive' | 'warning'
}): JSX.Element {
    const activeTab = tabs.find((tab) => tab.key === activeKey)

    return (
        <>
            <Tabs
                value={activeKey}
                onValueChange={(value) => onChange(value as ExperimentTab)}
                className="mt-4 border-b border-border"
                data-quill
            >
                <TabsList variant="line" className="max-w-full justify-start overflow-x-auto">
                    {tabs.map(({ key, label, count }) => (
                        <TabsTrigger key={key} value={key}>
                            {label}
                            {!!count && (
                                <Badge
                                    variant={badgeVariant}
                                    aria-label={pluralize(count, `${label.toLowerCase()} issue`)}
                                >
                                    {count}
                                </Badge>
                            )}
                        </TabsTrigger>
                    ))}
                </TabsList>
            </Tabs>
            <div className="mx-auto w-full max-w-350 pt-4">{activeTab?.content}</div>
        </>
    )
}
