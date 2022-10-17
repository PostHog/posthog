import React from 'react'
import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { LemonSwitch, Link } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'

export function SessionRecording(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <>
            <h2 id="recordings" className="subtitle">
                Recordings
            </h2>
            <p>
                Watch recordings of how users interact with your web app to see what can be improved. Recordings are
                found in the <Link to={urls.sessionRecordings()}>recordings page</Link>.
            </p>
            <p>
                Please note <b>your website needs to have</b> the <a href="#snippet">PostHog snippet</a> or the latest
                version of{' '}
                <a
                    href="https://posthog.com/docs/integrations/js-integration?utm_campaign=session-recording&utm_medium=in-product"
                    target="_blank"
                >
                    posthog-js
                </a>{' '}
                <b>directly</b> installed. For more details, check out our{' '}
                <a
                    href="https://posthog.com/docs/user-guides/recordings?utm_campaign=session-recording&utm_medium=in-product"
                    target="_blank"
                >
                    docs
                </a>
                .
            </p>
            <LemonSwitch
                data-attr="opt-in-session-recording-switch"
                onChange={(checked) => {
                    updateCurrentTeam({ session_recording_opt_in: checked })
                }}
                checked={!!currentTeam?.session_recording_opt_in}
                label="Record user sessions"
                bordered
            />

            {currentTeam?.session_recording_opt_in ? (
                <>
                    <h3 className="my-6" id="urls">
                        Capture console logs within recordings
                    </h3>
                    <p>
                        This setting controls if browser console logs wil captured as a part of recordings. The console
                        logs will be shown in the recording player to help you debug any issues.
                    </p>
                    <LemonSwitch
                        data-attr="opt-in-capture-console-log-switch"
                        onChange={(checked) => {
                            updateCurrentTeam({ capture_console_log_opt_in: checked })
                        }}
                        checked={!!currentTeam?.capture_console_log_opt_in}
                        label="Capture console logs"
                        bordered
                    />
                    <h3 className="my-6" id="urls">
                        Authorized domains for recordings
                    </h3>
                    <p>
                        Use the settings below to restrict the domains where recordings will be captured. If no domains
                        are selected, then there will be no domain restriction.
                    </p>
                    <p>
                        <b>Domains and wilcard subdomains are allowed</b> (example: <code>https://*.example.com</code>).
                        However, wildcarded top-level domains cannot be used (for security reasons).
                    </p>
                    <AuthorizedUrlList type={AuthorizedUrlListType.RECORDING_DOMAINS} />
                </>
            ) : null}
        </>
    )
}
