import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton, LemonTab, LemonTabs } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { FleetTab } from '../components/FleetTab'
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

function ComingSoon({ label }: { label: string }): JSX.Element {
    return <div className="text-muted py-8 text-center">{label} tab — coming next.</div>
}

export function CSMHudScene(): JSX.Element {
    const { canAccess, fleetLoading } = useValues(csmHudSceneLogic)
    const { loadFleet } = useActions(csmHudSceneLogic)
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
            content: <ComingSoon label="Renewals" />,
            link: urls.csmHudRenewals(),
        },
        {
            key: 'engagement',
            label: 'Engagement',
            content: <ComingSoon label="Engagement" />,
            link: urls.csmHudEngagement(),
        },
        {
            key: 'conversations',
            label: 'Conversations',
            content: <ComingSoon label="Conversations" />,
            link: urls.csmHudConversations(),
        },
        {
            key: 'expansion',
            label: 'Expansion',
            content: <ComingSoon label="Expansion" />,
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
                    <LemonButton type="secondary" loading={fleetLoading} onClick={() => loadFleet()}>
                        Refresh
                    </LemonButton>
                }
            />
            <LemonTabs activeKey={activeTab} tabs={tabs} sceneInset />
        </SceneContent>
    )
}

export default CSMHudScene
