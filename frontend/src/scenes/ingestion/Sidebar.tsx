import React from 'react'
import posthogLogo from 'public/posthog-logo.png'
import { ingestionLogic } from './ingestionLogic'
import { useActions, useValues } from 'kea'
import './IngestionWizard.scss'
import { InviteMembersButton, SitePopover } from '~/layout/navigation/TopBar/SitePopover'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { IconArticle, IconQuestionAnswer } from 'lib/components/icons'
import { HelpType } from '~/types'
import { LemonDivider } from 'lib/components/LemonDivider'

const HELP_UTM_TAGS = '?utm_medium=in-product-onboarding&utm_campaign=help-button-sidebar'

export function Sidebar(): JSX.Element {
    const { currentIndex, platform } = useValues(ingestionLogic)
    const { setVerify, setPlatform } = useActions(ingestionLogic)
    const { reportIngestionHelpClicked } = useActions(eventUsageLogic)

    return (
        <div className="IngestionSidebar">
            <div className="IngestionSidebar__content">
                <div style={{ paddingLeft: 8 }}>
                    <img src={posthogLogo} style={{ width: 157, height: 30 }} />
                </div>
                <div className="IngestionSidebar__steps">
                    <b>
                        <div
                            className={`mb ${currentIndex === 0 && 'ingestion-current-nav-step'}`}
                            onClick={() => setPlatform(null)}
                        >
                            <span>Get started</span>
                        </div>
                        <div
                            className={`mb ${currentIndex === 1 && 'ingestion-current-nav-step'} ${
                                !platform && 'nonclickable'
                            }`}
                            onClick={() => setVerify(false)}
                        >
                            <span>Connect your product</span>
                        </div>
                        <div
                            className={`mb ${currentIndex === 2 && 'ingestion-current-nav-step'} ${
                                !platform && 'nonclickable'
                            }`}
                            onClick={() => {
                                if (platform) {
                                    setVerify(true)
                                }
                            }}
                        >
                            <span>Listen for events</span>
                        </div>
                    </b>
                </div>
                <div className="sidebar-bottom">
                    <div className="popover mb">
                        <SitePopover />
                    </div>
                    <InviteMembersButton />
                    <div className="sidebar-help">
                        <LemonDivider thick dashed />
                        <a href={`https://posthog.com/slack${HELP_UTM_TAGS}`} rel="noopener" target="_blank">
                            <LemonButton
                                icon={<IconQuestionAnswer style={{ color: 'var(--primary)' }} />}
                                type="tertiary"
                                fullWidth
                                style={{ marginTop: '1.5em', color: 'var(--primary)' }}
                                onClick={() => {
                                    reportIngestionHelpClicked(HelpType.Slack)
                                }}
                            >
                                Get support on Slack
                            </LemonButton>
                        </a>
                        <a
                            href={`https://posthog.com/docs/integrate/ingest-live-data${HELP_UTM_TAGS}`}
                            rel="noopener"
                            target="_blank"
                        >
                            <LemonButton
                                icon={<IconArticle style={{ color: 'var(--primary)' }} />}
                                type="tertiary"
                                style={{ color: 'var(--primary)' }}
                                fullWidth
                                onClick={() => {
                                    reportIngestionHelpClicked(HelpType.Docs)
                                }}
                            >
                                Read our documentation
                            </LemonButton>
                        </a>
                    </div>
                </div>
            </div>
        </div>
    )
}
