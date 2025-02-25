import { IconArrowLeft, IconGear, IconSidePanel } from '@posthog/icons'
import { BindLogic, useActions, useValues } from 'kea'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSettingsLogic'
import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { SidePanelTab } from '~/types'

import { Intro } from './Intro'
import { maxGlobalLogic } from './maxGlobalLogic'
import { maxLogic } from './maxLogic'
import { QuestionInput } from './QuestionInput'
import { QuestionSuggestions } from './QuestionSuggestions'
import { Thread } from './Thread'

export const scene: SceneExport = {
    component: Max,
    logic: maxGlobalLogic,
}

export function Max(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { sidePanelOpen, selectedTab } = useValues(sidePanelLogic)
    const { closeSidePanel } = useActions(sidePanelLogic)

    if (!featureFlags[FEATURE_FLAGS.ARTIFICIAL_HOG]) {
        return <NotFound object="page" caption="You don't have access to AI features yet." />
    }

    if (sidePanelOpen && selectedTab === SidePanelTab.Max) {
        return (
            <div className="flex flex-col items-center justify-center w-full grow">
                <IconSidePanel className="text-3xl text-muted mb-2" />
                <h3 className="text-xl font-bold mb-1">Max is currently in the sidebar</h3>
                <p className="text-sm text-muted mb-2">You can navigate freely around the app, or…</p>
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    onClick={() => closeSidePanel()}
                    sideIcon={<IconArrowLeft />}
                >
                    Get him in here
                </LemonButton>
            </div>
        )
    }

    return (
        <BindLogic logic={maxLogic} props={{ conversationId: null }}>
            <MaxInstance />
        </BindLogic>
    )
}

export function MaxInstance(): JSX.Element {
    const { threadGrouped } = useValues(maxLogic)
    const { openSettingsPanel } = useActions(sidePanelSettingsLogic)

    const headerButtons = (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconGear />}
            onClick={() => {
                openSettingsPanel({ settingId: 'core-memory' })
                setTimeout(() => document.getElementById('product-description-textarea')?.focus(), 1)
            }}
        >
            Settings
        </LemonButton>
    )

    return (
        <>
            <PageHeader delimited buttons={headerButtons} />
            {!threadGrouped.length ? (
                <div className="@container/max-welcome relative flex flex-col gap-3 px-4 pb-8 items-center grow justify-center">
                    <Intro />
                    <QuestionInput />
                    <QuestionSuggestions />
                </div>
            ) : (
                <>
                    <Thread />
                    <QuestionInput />
                </>
            )}
        </>
    )
}
