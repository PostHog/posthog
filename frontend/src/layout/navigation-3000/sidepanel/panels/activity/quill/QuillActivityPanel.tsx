import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconNotification } from '@posthog/icons'
import {
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Tabs,
    TabsList,
    TabsTrigger,
} from '@posthog/quill'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { userLogic } from 'scenes/userLogic'

import {
    SidePanelActivityTab,
    sidePanelActivityLogic,
} from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelActivityLogic'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { AccessControlLevel, AccessControlResourceType, AvailableFeature } from '~/types'

import { QuillActivityControls } from './QuillActivityControls'
import { QuillActivityList } from './QuillActivityList'
import { QuillActivityMetalytics } from './QuillActivityMetalytics'

const SCROLL_TRIGGER_OFFSET = 100

export function QuillActivityPanel(): JSX.Element {
    const { activeTab, contextFromPage } = useValues(sidePanelActivityLogic)
    const { setActiveTab, maybeLoadOlderActivity } = useActions(sidePanelActivityLogic)
    const { user } = useValues(userLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { selectedTabOptions } = useValues(sidePanelStateLogic)
    const lastScrollTopRef = useRef(0)
    const showAnalytics = !!featureFlags[FEATURE_FLAGS.METALYTICS]
    // The tab is persisted, so it can hold one this panel doesn't show. Anything else lands on Activity.
    const shownTab =
        activeTab === SidePanelActivityTab.Metalytics && showAnalytics ? activeTab : SidePanelActivityTab.All

    // Each open starts on Activity, unless the panel was opened straight to Analytics.
    useOnMountEffect(() => {
        if (!(showAnalytics && selectedTabOptions === SidePanelActivityTab.Metalytics)) {
            setActiveTab(SidePanelActivityTab.All)
        }
    })

    if (!userHasAccess(AccessControlResourceType.ActivityLog, AccessControlLevel.Viewer)) {
        return (
            <Empty className="flex-1">
                <EmptyHeader>
                    <EmptyMedia variant="icon">
                        <IconNotification />
                    </EmptyMedia>
                    <EmptyTitle>You can't view activity logs</EmptyTitle>
                    <EmptyDescription>Ask a project admin to give you access to activity logs.</EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }

    const onScroll = (event: React.UIEvent<HTMLDivElement>): void => {
        const { scrollTop, clientHeight, scrollHeight } = event.currentTarget
        // Only scrolling down toward the end loads older entries.
        if (scrollTop > lastScrollTopRef.current && scrollHeight - (scrollTop + clientHeight) < SCROLL_TRIGGER_OFFSET) {
            maybeLoadOlderActivity()
        }
        lastScrollTopRef.current = scrollTop
    }

    return (
        <PayGateMini
            feature={AvailableFeature.AUDIT_LOGS}
            featureDetail="activity-log-side-panel"
            className="flex min-h-0 flex-1 flex-col"
            overrideShouldShowGate={user?.is_impersonated || !!featureFlags[FEATURE_FLAGS.AUDIT_LOGS_ACCESS]}
        >
            <div className="flex min-h-0 flex-1 flex-col">
                <div className="flex shrink-0 flex-col gap-2 p-3 pb-2">
                    {showAnalytics && (
                        <Tabs value={shownTab} onValueChange={(value) => setActiveTab(value as SidePanelActivityTab)}>
                            <TabsList className="w-full">
                                <TabsTrigger value={SidePanelActivityTab.All}>Activity</TabsTrigger>
                                <TabsTrigger value={SidePanelActivityTab.Metalytics}>Analytics</TabsTrigger>
                            </TabsList>
                        </Tabs>
                    )}
                    {shownTab === SidePanelActivityTab.All && contextFromPage?.scope && (
                        <QuillActivityControls contextFromPage={contextFromPage} />
                    )}
                </div>
                <div
                    className="min-h-0 flex-1 overflow-y-auto scroll-mask-y-4 scroll-py-4 px-3 pb-3"
                    onScroll={onScroll}
                >
                    {shownTab === SidePanelActivityTab.Metalytics ? <QuillActivityMetalytics /> : <QuillActivityList />}
                </div>
            </div>
        </PayGateMini>
    )
}
