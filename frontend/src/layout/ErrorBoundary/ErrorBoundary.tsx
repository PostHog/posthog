import { ErrorBoundary as SentryErrorBoundary } from '@sentry/react'
import { HelpButton } from 'lib/components/HelpButton/HelpButton'
import { IconArrowDropDown } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'
import './ErrorBoundary.scss'

export function ErrorBoundary({ children }: { children: React.ReactElement }): JSX.Element {
    return (
        <SentryErrorBoundary
            fallback={({ error, eventId }) => {
                // Get the names of functions (including React compnents) in the stack trace
                let stackNames = (error.stack || '')
                    .split('\n')
                    .filter((l) => l.startsWith('    at'))
                    .map((l) => l.split(' ')[5])
                // Stop if we find the start of React's render loop
                stackNames = stackNames.slice(0, stackNames.indexOf('renderWithHooks'))

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
                                {stackNames.length > 0 ? <code>{['', ...stackNames].join('\n> ')}</code> : null}
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
