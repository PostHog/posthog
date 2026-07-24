import { useActions } from 'kea'

import { IconGear, IconPeople, IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { captureQuickstartAction } from './captureQuickstartAction'
import { ProjectTokenChip } from './ProjectTokenChip'
import { WorkspaceStrip } from './WorkspaceStrip'

/** The page chrome both variants share; the slot next to the token chip is the only difference. */
export function QuickstartHeader({ installStatus }: { installStatus?: React.ReactNode }): JSX.Element {
    const { showInviteModal } = useActions(inviteLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)

    return (
        <div className="flex flex-col gap-4">
            <WorkspaceStrip />
            {/* Standard scene header: title left, actions right. This page is a recurring
                homepage, so it gets utility, not a one-time welcome ceremony. */}
            <section>
                <div className="flex flex-wrap items-center justify-between gap-x-8 gap-y-2">
                    <h1 className="text-2xl font-bold mb-0">Quickstart</h1>
                    <div className="flex flex-wrap items-center gap-2">
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconSparkles />}
                            onClick={() => {
                                captureQuickstartAction('ask_posthog_ai_header')
                                openSidePanel(SidePanelTab.Max)
                            }}
                            data-attr="quickstart-header-ask-posthog-ai"
                        >
                            Ask PostHog AI
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconPeople />}
                            onClick={() => {
                                captureQuickstartAction('invite_teammate_header')
                                showInviteModal()
                            }}
                            data-attr="quickstart-header-invite"
                        >
                            Invite teammates
                        </LemonButton>
                        <LemonButton
                            size="small"
                            icon={<IconGear />}
                            to={urls.settings('project')}
                            onClick={() => captureQuickstartAction('open_project_settings_header')}
                            data-attr="quickstart-header-settings"
                        >
                            Project settings
                        </LemonButton>
                    </div>
                </div>
                <p className="text-secondary mb-0 mt-1 max-w-140">
                    Connect your product's context, configure Tools, and choose how you work with PostHog.
                </p>
                <div className="mt-3 flex flex-wrap items-stretch gap-2">
                    <ProjectTokenChip />
                    {installStatus}
                </div>
            </section>
        </div>
    )
}
