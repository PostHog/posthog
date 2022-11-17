import { ErrorBoundary as SentryErrorBoundary } from '@sentry/react'
import { HelpButton } from 'lib/components/HelpButton/HelpButton'
import { IconArrowDropDown } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'
import './ErrorBoundary.scss'

export function ErrorBoundary({ children }: { children: React.ReactElement }): JSX.Element {
    return (
        <SentryErrorBoundary
            fallback={({ error, eventId }) => {
                let lines = (error.stack || '')
                    .split('\n')
                    .filter((l) => l.startsWith('    at'))
                    .map((l) => l.split(' ')[5])
                lines = lines.slice(0, lines.indexOf('renderWithHooks'))

                return (
                    <div className="ErrorBoundary">
                        <>
                            <h2>An error has occurred</h2>
                            <pre>
                                <code>
                                    {error.name} (ID {eventId})
                                    <br />
                                    {error.message}
                                </code>
                                {lines.length > 0 ? (
                                    <code>
                                        {'\n> '}
                                        {lines.join('\n> ')}
                                    </code>
                                ) : null}
                            </pre>
                            We've registered this event for analysis, but feel free to contact us directly too.
                            <HelpButton
                                customComponent={
                                    <LemonButton type="primary" sideIcon={<IconArrowDropDown />}>
                                        Contact PostHog
                                    </LemonButton>
                                }
                                customKey="error-boundary"
                                contactOnly
                            />
                        </>
                    </div>
                )
            }}
        >
            {children}
        </SentryErrorBoundary>
    )
}
