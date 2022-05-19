import React from 'react'
import posthogLogo from 'public/posthog-logo.png'
import { ingestionLogic } from './ingestionLogic'
import { useActions, useValues } from 'kea'
import './IngestionWizard.scss'
import { InviteMembersButton, SitePopover } from '~/layout/navigation/TopBar/SitePopover'

export function Sidebar(): JSX.Element {
    const { currentIndex, platform } = useValues(ingestionLogic)
    const { setVerify, setPlatform } = useActions(ingestionLogic)

    return (
        <div
            style={{ background: 'white', width: 300, display: 'flex', flexDirection: 'column', position: 'relative' }}
        >
            <div style={{ display: 'flex', flexDirection: 'column', height: '100%', position: 'fixed' }}>
                <div style={{ padding: '2em' }}>
                    <img src={posthogLogo} style={{ width: 157, height: 30 }} />
                </div>
                <div className="IngestionSidebar__steps" style={{ fontSize: 14, padding: '2em' }}>
                    <b>
                        <div
                            className={`mb ${currentIndex === 0 && 'ingestion-current-nav-step'}`}
                            onClick={() => setPlatform(null)}
                        >
                            {currentIndex === 0 && <div className="step-indicator" />}
                            <span>Get started</span>
                        </div>
                        <div
                            className={`mb ${currentIndex === 1 && 'ingestion-current-nav-step'} ${
                                !platform && 'nonclickable'
                            }`}
                            onClick={() => setVerify(false)}
                        >
                            {currentIndex === 1 && <div className="step-indicator" />}
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
                            {currentIndex === 2 && <div className="step-indicator" />}
                            <span>Listen for events</span>
                        </div>
                    </b>
                </div>
                <div className="sidebar-bottom">
                    <InviteMembersButton />
                    <div className="sidebar-help">
                        <SitePopover />
                        <a style={{ marginBottom: '1.5em', marginTop: '1.5em' }}>Get support on Slack</a>
                        <a>Read our documentation</a>
                    </div>
                </div>
            </div>
        </div>
    )
}
