import { LemonBanner, LemonCheckbox, Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { useState } from 'react'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

export function CSPReportingSettings(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

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
            <p>
                <LemonBanner type="info">
                    We accept some additional parameters on the report URL. Some of these require that you add
                    information when generating the headers for your pages. <Link>See our docs for some examples.</Link>
                </LemonBanner>
                <div>
                    <LemonCheckbox
                        label="session_id: the PostHog UUIDv7 session id"
                        checked={includeSessionId}
                        onChange={setIncludeSessionId}
                    />
                    <LemonCheckbox
                        label="distinct_id: the distinct id for the current user"
                        checked={includeDistinctId}
                        onChange={setIncludeDistinctId}
                    />
                    <LemonCheckbox
                        label="version: the version for the current CSP"
                        checked={includeVersion}
                        onChange={setIncludeVersion}
                    />
                    <LemonCheckbox
                        label="sample_rate: the sample rate for the current CSP"
                        checked={includeSampleRate}
                        onChange={setIncludeSampleRate}
                    />
                </div>
            </p>
            <div className="gap-y-2">
                <p>Set this URL for both the report-to and report-uri endpoints</p>
                <CodeSnippet language={Language.Text} wrap={true}>
                    {urls.absolute(
                        combineUrl('/api/cspr', {
                            token: currentTeam?.api_token,
                            v: includeVersion ? 1 : undefined,
                            session_id: includeSessionId ? 'ADD_THE_SESSION_ID' : undefined,
                            distinct_id: includeDistinctId ? 'ADD_THE_DISTINCT_ID' : undefined,
                            sample_rate: includeSampleRate ? '0.5' : undefined,
                        }).url
                    )}
                </CodeSnippet>
            </div>
        </>
    )
}
