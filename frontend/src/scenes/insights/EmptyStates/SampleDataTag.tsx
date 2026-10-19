import { useValues } from 'kea'

import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { setupWizardStatusLogic } from 'scenes/onboarding/shared/setupWizardStatusLogic'

export function SampleDataTag(): JSX.Element {
    const { setupStatus } = useValues(setupWizardStatusLogic)

    const content = (
        <div className="max-w-72 space-y-1.5 p-0.5">
            <div className="font-semibold">This is sample data</div>
            <p className="m-0">
                This project hasn't received any events yet - you'll see your real data here as soon as events start
                coming in.
            </p>
            {setupStatus?.kind === 'installing' &&
                (setupStatus.mode === 'cloud' ? (
                    <p className="m-0">
                        The setup wizard is installing PostHog in your codebase. Once it's done, it will open a pull
                        request for you to merge.
                    </p>
                ) : (
                    <p className="m-0">
                        The setup wizard is installing PostHog in your codebase. You'll see real data here soon after
                        it's done.
                    </p>
                ))}
            {setupStatus?.kind === 'pull_request' &&
                (setupStatus.pullRequest.merged ? (
                    <p className="m-0">
                        Your setup pull request is merged. Once the updated code is live and sending events, this chart
                        will fill in automatically.
                    </p>
                ) : (
                    <p className="m-0">
                        Your setup pull request hasn't been merged yet -{' '}
                        <Link to={setupStatus.pullRequest.url} target="_blank" targetBlankIcon>
                            merge it
                        </Link>{' '}
                        to start sending events.
                    </p>
                ))}
        </div>
    )
    return (
        <Tooltip title={content} interactive delayMs={100} placement="bottom">
            <LemonTag data-attr="insight-sample-data-tag" className="cursor-help" type="muted">
                Sample data
            </LemonTag>
        </Tooltip>
    )
}
