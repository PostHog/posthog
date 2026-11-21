import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonTab, LemonTabs, LemonTag } from '@posthog/lemon-ui'
import { Badge, Tabs, TabsContent, TabsList, TabsTrigger } from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { IntercomImportSection } from './IntercomImportSection'
import { PylonImportSection } from './PylonImportSection'
import { ZendeskImportSection } from './ZendeskImportSection'

type ImportTabKey = 'zendesk' | 'intercom' | 'pylon'

const DEFAULT_IMPORT_TAB: ImportTabKey = 'zendesk'

export function ImportsSection(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { location, hashParams, searchParams } = useValues(router)
    const pylonEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_PYLON_IMPORT]
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const betaTag = todayRailNav ? (
        <Badge variant="info" className="ml-1">
            Beta
        </Badge>
    ) : (
        <LemonTag type="highlight" size="small" className="ml-1">
            Beta
        </LemonTag>
    )

    const tabs: (LemonTab<ImportTabKey> | false)[] = [
        {
            key: 'zendesk',
            label: 'Zendesk',
            content: <ZendeskImportSection />,
        },
        {
            key: 'intercom',
            label: (
                <>
                    Intercom
                    {betaTag}
                </>
            ),
            content: <IntercomImportSection />,
        },
        pylonEnabled && {
            key: 'pylon',
            label: (
                <>
                    Pylon
                    {betaTag}
                </>
            ),
            content: <PylonImportSection />,
        },
    ]
    const activeTab =
        tabs.find((tab): tab is LemonTab<ImportTabKey> => !!tab && tab.key === hashParams.import)?.key ??
        DEFAULT_IMPORT_TAB

    const setTab = (tab: ImportTabKey): void => {
        router.actions.replace(location.pathname, searchParams, { ...hashParams, import: tab })
    }

    if (todayRailNav) {
        const visibleTabs = tabs.filter((tab): tab is LemonTab<ImportTabKey> => !!tab)

        return (
            <Tabs value={activeTab} onValueChange={(key) => setTab(key as ImportTabKey)}>
                <TabsList variant="line">
                    {visibleTabs.map((tab) => (
                        <TabsTrigger key={tab.key} value={tab.key}>
                            {tab.label}
                        </TabsTrigger>
                    ))}
                </TabsList>
                {visibleTabs.map((tab) => (
                    <TabsContent key={tab.key} value={tab.key}>
                        {'content' in tab ? tab.content : null}
                    </TabsContent>
                ))}
            </Tabs>
        )
    }

    return <LemonTabs activeKey={activeTab} onChange={(key) => setTab(key)} tabs={tabs} />
}
