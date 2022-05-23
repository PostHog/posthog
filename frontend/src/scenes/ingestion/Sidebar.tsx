import React from 'react'
import { ingestionLogic } from './ingestionLogic'
import { useActions, useValues } from 'kea'
import './IngestionWizard.scss'
import { InviteMembersButton } from '~/layout/navigation/TopBar/SitePopover'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { IconArticle, IconQuestionAnswer } from 'lib/components/icons'
import { HelpType } from '~/types'
import { LemonDivider } from 'lib/components/LemonDivider'
import { FriendlyLogo } from '~/toolbar/assets/FriendlyLogo'

const HELP_UTM_TAGS = '?utm_medium=in-product-onboarding&utm_campaign=help-button-sidebar'

export function Sidebar(): JSX.Element {
    const { currentIndex, platform } = useValues(ingestionLogic)
    const { setVerify, setPlatform } = useActions(ingestionLogic)
    const { reportIngestionHelpClicked } = useActions(eventUsageLogic)

    return (
        <div className="IngestionSidebar">
            <div className="IngestionSidebar__content">
                <div style={{ marginLeft: -4 }}>
                    <FriendlyLogo style={{ fontSize: '1.125rem' }} />
                </div>
                <div className="IngestionSidebar__steps">
                    <LemonButton
                        fullWidth
                        className={`${currentIndex === 0 && 'ingestion-current-nav-step'}`}
                        onClick={() => setPlatform(null)}
                    >
                        Get started
                    </LemonButton>
                    <LemonButton
                        fullWidth
                        className={`${currentIndex === 1 && 'ingestion-current-nav-step'}`}
                        disabled={!platform}
                        onClick={() => {
                            if (platform && currentIndex !== 1) {
                                setVerify(false)
                            }
                        }}
                    >
                        Connect your product
                    </LemonButton>
                    <LemonButton
                        fullWidth
                        className={`${currentIndex === 2 && 'ingestion-current-nav-step'}`}
                        disabled={!platform}
                        onClick={() => {
                            if (platform) {
                                setVerify(true)
                            }
                        }}
                    >
                        Listen for events
                    </LemonButton>
                </div>
                <div className="IngestionSidebar__bottom">
                    <InviteMembersButton />
                    <div className="IngestionSidebar__help">
                        <LemonDivider thick dashed style={{ color: 'var(--border)', opacity: 100 }} />
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
