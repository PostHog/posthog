import { useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { useState } from 'react'

import { IconInfo } from '@posthog/icons'
import { LemonBanner, LemonCheckbox, Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { domainFor, proxyLogic } from 'scenes/settings/environment/proxyLogic'
import { teamLogic } from 'scenes/teamLogic'

export function CSPReportingSettings(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    const { proxyRecords } = useValues(proxyLogic)
    const proxyRecord = domainFor(proxyRecords[0])

    const [includeSessionId, setIncludeSessionId] = useState(false)
    const [includeDistinctId, setIncludeDistinctId] = useState(false)
    const [includeVersion, setIncludeVersion] = useState(true)
    const [includeSampleRate, setIncludeSampleRate] = useState(false)

    return (
        <>
            <p>
                A CSP is an instruction to the browser on what assets are allowed to be loaded and what domains your
                site can send information to. It's a very powerful security mechanism, that can be super tricky to
                configure.
            </p>
            <p>
                CSP Reporting lets you track your CSP by sending reports to PostHog when a CSP violation occurs. This
                helps you see when CSP misconfiguration, web site changes, or security flaws are causing problems.
            </p>
            <p>
                PostHog supports both the{' '}
                <Link
                    to="https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/report-uri"
                    target="_blank"
                >
                    report-uri
                </Link>{' '}
                and{' '}
                <Link
                    to="https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/report-to"
                    target="_blank"
                >
                    report-to
                </Link>{' '}
                directives, converting violations into an event. Letting you track and alert on them just like any other
                event.
            </p>
            <div className="flex flex-col gap-2">
                <LemonBanner type="info" hideIcon={true}>
                    <div className="flex flex-row items-center gap-x-2">
                        <IconInfo />
                        <div>
                            We accept some additional parameters on the report URL. These require that you add
                            information when adding the URL to your pages.{' '}
                            <Link to="https://posthog.com/docs/csp-tracking">See our docs for some examples.</Link>
                        </div>
                    </div>
                </LemonBanner>
                <div>
                    <LemonCheckbox
                        label="version: the version for the current CSP. This helps you track impact of changes to your CSP."
                        checked={includeVersion}
                        onChange={setIncludeVersion}
                    />
                    <LemonCheckbox
                        label="session_id: the PostHog UUIDv7 session id. Helps you link CSP violations to session replay."
                        checked={includeSessionId}
                        onChange={setIncludeSessionId}
                    />
                    <LemonCheckbox
                        label="distinct_id: the distinct id for the current user. So you can track which users are being affected"
                        checked={includeDistinctId}
                        onChange={setIncludeDistinctId}
                    />
                    <LemonCheckbox
                        label="sample_rate: the sample rate for the current CSP. Lets you control the volume of reports you ingest."
                        checked={includeSampleRate}
                        onChange={setIncludeSampleRate}
                    />
                </div>
            </div>
            <div className="flex flex-col gap-y-2">
                <p>Set this URL for both the report-to and report-uri endpoints</p>
                <CodeSnippet language={Language.Text} wrap={true}>
                    {
                        combineUrl(`${proxyRecord}/report/`, {
                            token: currentTeam?.api_token,
                            v: includeVersion ? 1 : undefined,
                            session_id: includeSessionId ? 'ADD_THE_SESSION_ID' : undefined,
                            distinct_id: includeDistinctId ? 'ADD_THE_DISTINCT_ID' : undefined,
                            sample_rate: includeSampleRate ? '0.5' : undefined,
                        }).url
                    }
                </CodeSnippet>
            </div>
        </>
    )
}
