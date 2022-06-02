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

const HELP_UTM_TAGS = '?utm_medium=in-product-onboarding&utm_campaign=help-button-sidebar'

export function Sidebar(): JSX.Element {
    const { currentIndex, platform } = useValues(ingestionLogic)
    const { setVerify, setPlatform } = useActions(ingestionLogic)
    const { reportIngestionHelpClicked } = useActions(eventUsageLogic)

    return (
        <div className="IngestionSidebar">
            <div className="IngestionSidebar__content">
                <div className="IngestionSidebar__steps">
                    <LemonButton active={currentIndex === 0} onClick={() => setPlatform(null)}>
                        Get started
                    </LemonButton>
                    <LemonButton
                        active={currentIndex === 1}
                        disabled={!platform}
                        onClick={() => {
                            if (platform) {
                                setVerify(false)
                                setPlatform(platform)
                            }
                        }}
                    >
                        Connect your product
                    </LemonButton>
                    <LemonButton
                        active={currentIndex === 2}
                        disabled={currentIndex !== 2}
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
                    <InviteMembersButton center={true} type="primary" />
                    <LemonDivider thick dashed large style={{ marginTop: 24, marginBottom: 24 }} />
                    <div className="IngestionSidebar__help">
                        <a href={`https://posthog.com/slack${HELP_UTM_TAGS}`} rel="noopener" target="_blank">
                            <LemonButton
                                icon={<IconQuestionAnswer style={{ color: 'var(--primary)' }} />}
                                type="tertiary"
                                fullWidth
                                style={{
                                    color: 'var(--primary)',
                                    background: 'none',
                                    padding: 0,
                                    minHeight: 'auto',
                                }}
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
                            className="mt-05"
                        >
                            <LemonButton
                                icon={<IconArticle style={{ color: 'var(--primary)' }} />}
                                type="tertiary"
                                style={{
                                    color: 'var(--primary)',
                                    background: 'none',
                                    paddingLeft: 0,
                                    minHeight: 'auto',
                                }}
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
