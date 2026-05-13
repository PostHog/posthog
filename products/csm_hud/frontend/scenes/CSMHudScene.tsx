import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton, LemonInput, LemonTab, LemonTabs } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ConversationsTab } from '../components/ConversationsTab'
import { EngagementTab } from '../components/EngagementTab'
import { ExpansionTab } from '../components/ExpansionTab'
import { FleetTab } from '../components/FleetTab'
import { MissingSourcesBanner } from '../components/MissingSourcesBanner'
import { RenewalsTab } from '../components/RenewalsTab'
import { csmHudSceneLogic } from '../logics/csmHudSceneLogic'

type TabKey = 'fleet' | 'renewals' | 'engagement' | 'conversations' | 'expansion'

const TAB_KEYS: readonly TabKey[] = ['fleet', 'renewals', 'engagement', 'conversations', 'expansion']

function tabFromPath(pathname: string): TabKey {
    // pathname is project-prefixed at runtime (`/project/<id>/csm-hud/<tab>`);
    // suffix match keeps the lookup project-id-agnostic.
    for (const key of TAB_KEYS) {
        if (pathname.endsWith(`/csm-hud/${key}`)) {
            return key
        }
    }
    return 'fleet'
}

export const scene: SceneExport = {
    component: CSMHudScene,
    logic: csmHudSceneLogic,
}

export function CSMHudScene(): JSX.Element {
    const { canAccess, fleetLoading, csmFilter, user } = useValues(csmHudSceneLogic)
    const { loadFleet, setCsmFilter } = useActions(csmHudSceneLogic)
    const { location } = useValues(router)

    if (!canAccess) {
        return <NotFound object="page" />
    }

    const activeTab: TabKey = tabFromPath(location.pathname)

    const tabs: LemonTab<TabKey>[] = [
        { key: 'fleet', label: 'Fleet', content: <FleetTab />, link: urls.csmHudFleet() },
        {
            key: 'renewals',
            label: 'Renewals',
            content: <RenewalsTab />,
            link: urls.csmHudRenewals(),
        },
        {
            key: 'engagement',
            label: 'Engagement',
            content: <EngagementTab />,
            link: urls.csmHudEngagement(),
        },
        {
            key: 'conversations',
            label: 'Conversations',
            content: <ConversationsTab />,
            link: urls.csmHudConversations(),
        },
        {
            key: 'expansion',
            label: 'Expansion',
            content: <ExpansionTab />,
            link: urls.csmHudExpansion(),
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name="CSM HUD"
                description="Customer Success Manager portfolio dashboard."
                resourceType={{ type: 'csm_hud' }}
                actions={
                    <div className="flex items-center gap-2">
                        <LemonInput
                            type="search"
                            value={csmFilter}
                            onChange={setCsmFilter}
                            placeholder="Filter to CSM email (blank = all)"
                            size="small"
                            className="w-72"
                        />
                        {user?.email && csmFilter !== user.email && (
                            <LemonButton type="tertiary" size="small" onClick={() => setCsmFilter(user.email)}>
                                Mine
                            </LemonButton>
                        )}
                        <LemonButton type="secondary" loading={fleetLoading} onClick={() => loadFleet()}>
                            Refresh
                        </LemonButton>
                    </div>
                }
            />
            <MissingSourcesBanner />
            <LemonTabs activeKey={activeTab} tabs={tabs} sceneInset />
        </SceneContent>
    )
}

export default CSMHudScene
