import { IconArrowLeft, IconExternal, IconGear, IconPlus, IconSidePanel } from '@posthog/icons'
import { BindLogic, useActions, useValues } from 'kea'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SidePanelPaneHeader } from '~/layout/navigation-3000/sidepanel/components/SidePanelPaneHeader'
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

export interface MaxInstanceProps {
    sidePanel?: boolean
}

export function MaxInstance({ sidePanel }: MaxInstanceProps): JSX.Element {
    const { threadGrouped } = useValues(maxLogic)
    const { startNewConversation } = useActions(maxLogic)
    const { openSettingsPanel } = useActions(sidePanelSettingsLogic)
    const { closeSidePanel } = useActions(sidePanelLogic)

    const headerButtons = (
        <>
            <LemonButton
                size="small"
                icon={<IconPlus />}
                onClick={() => startNewConversation()}
                tooltip="Start a new chat"
                tooltipPlacement="bottom"
            />
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
        </>
    )

    return (
        <>
            {sidePanel && (
                <SidePanelPaneHeader>
                    <LemonButton
                        size="small"
                        sideIcon={<IconPlus />}
                        onClick={() => startNewConversation()}
                        tooltip="Start a new chat"
                        tooltipPlacement="bottom"
                    />
                    <div className="flex-1" />
                    <LemonButton
                        size="small"
                        sideIcon={<IconExternal />}
                        to={urls.max()}
                        onClick={() => closeSidePanel()}
                        tooltip="Open as main focus"
                        tooltipPlacement="bottom"
                    />
                </SidePanelPaneHeader>
            )}
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
