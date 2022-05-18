import React from 'react'
import posthogLogo from 'public/posthog-logo.png'
import { ingestionLogic } from './ingestionLogic'
import { useValues } from 'kea'
import './IngestionWizard.scss'
import { InviteMembersButton, SitePopover } from '~/layout/navigation/TopBar/SitePopover'

export function Sidebar(): JSX.Element {
    const { index } = useValues(ingestionLogic)

    return (
        <div
            style={{ background: 'white', width: 300, display: 'flex', flexDirection: 'column', position: 'relative' }}
        >
            <div style={{ display: 'flex', flexDirection: 'column', height: '100%', position: 'fixed' }}>
                <div style={{ padding: '2em' }}>
                    <img src={posthogLogo} style={{ width: 157, height: 30 }} />
                </div>
                <div className="text-muted-alt" style={{ fontSize: 14, padding: '2em' }}>
                    <b>
                        <div className={`mb ${index === 0 && 'ingestion-current-nav-step'}`}>
                            {index === 0 && <div className="step-indicator" />}
                            <span>Get started</span>
                        </div>
                        <div className="mb">Connect your product</div>
                        <div className="mb">Listen for events</div>
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
