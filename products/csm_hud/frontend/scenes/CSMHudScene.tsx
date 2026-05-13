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
import { RenewalsTab } from '../components/RenewalsTab'
import { csmHudSceneLogic } from '../logics/csmHudSceneLogic'

type TabKey = 'fleet' | 'renewals' | 'engagement' | 'conversations' | 'expansion'

const TAB_FROM_PATH: Record<string, TabKey> = {
    '/csm-hud/fleet': 'fleet',
    '/csm-hud/renewals': 'renewals',
    '/csm-hud/engagement': 'engagement',
    '/csm-hud/conversations': 'conversations',
    '/csm-hud/expansion': 'expansion',
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

    const activeTab: TabKey = TAB_FROM_PATH[location.pathname] ?? 'fleet'

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
            <LemonTabs activeKey={activeTab} tabs={tabs} sceneInset />
        </SceneContent>
    )
}

export default CSMHudScene
