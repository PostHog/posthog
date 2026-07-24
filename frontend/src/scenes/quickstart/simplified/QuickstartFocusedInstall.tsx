import { LemonButton } from '@posthog/lemon-ui'

import { QuickstartInstallSwitcher } from './QuickstartInstallSwitcher'

// Pre-ingestion view for the test2 arm: one job, get the first event in. All install
// methods live inline as a master-detail choice. There is no install detection: the user
// leaves this view themselves, and merging/deploying happen outside our sight.
export function QuickstartFocusedInstall({ onDismiss }: { onDismiss: () => void }): JSX.Element {
    const intro = (
        <div>
            <h2 className="text-lg font-semibold mb-1">Connect PostHog to your product</h2>
            <p className="text-secondary mb-0">
                Install the PostHog SDK to start sending data. The setup agent can write the integration for you, or you
                can install it yourself.
            </p>
        </div>
    )

    return (
        <section className="flex flex-col gap-4">
            <QuickstartInstallSwitcher intro={intro} />
            <div>
                <LemonButton type="secondary" size="small" onClick={onDismiss} data-attr="quickstart-install-continue">
                    Continue to PostHog
                </LemonButton>
            </div>
        </section>
    )
}
