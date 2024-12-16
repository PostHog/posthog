import { Spinner } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { errorTrackingIssueSceneLogic } from 'scenes/error-tracking/errorTrackingIssueSceneLogic'
import { getExceptionProperties } from 'scenes/error-tracking/utils'

export const OverviewPanel = (): JSX.Element => {
    const { issueProperties, issueLoading } = useValues(errorTrackingIssueSceneLogic)

    const _ = getExceptionProperties(issueProperties)

    return (
        <div className="px-1">
            {issueLoading ? (
                <Spinner />
            ) : (
                <div className="flex flex-row gap-2 flex-wrap">
                    {/* <LemonTag type="danger">{$exception_message}</LemonTag>
                    <TitledSnack
                        type="success"
                        title="captured by"
                        value={
                            $sentry_url ? (
                                <Link
                                    className="text-3000 hover:underline decoration-primary-alt cursor-pointer"
                                    to={$sentry_url}
                                    target="_blank"
                                >
                                    Sentry
                                </Link>
                            ) : (
                                'PostHog'
                            )
                        }
                    />
                    <TitledSnack title="synthetic" value={$exception_synthetic ? 'true' : 'false'} />
                    <TitledSnack title="library" value={`${$lib} ${$lib_version}`} />
                    <TitledSnack title="browser" value={$browser ? `${$browser} ${$browser_version}` : 'unknown'} />
                    <TitledSnack title="os" value={$os ? `${$os} ${$os_version}` : 'unknown'} /> */}
                </div>
            )}
        </div>
    )
    // <div className="italic">{issue?.description}</div>}</div>
}
