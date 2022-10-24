import { useValues } from 'kea'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { Realm } from '~/types'
import './FeedbackButton.scss'

function isOnPagesWithHighZIndex(): boolean {
    // currently the feedback apps isn't updating properly
    // it's occluded on the home page and the dashboard page
    // and so the feedback button should be hidden on those pages
    const brokenPageUrlFragments = ['/home', '/dashboard']
    return brokenPageUrlFragments.some((fragment) => window.location.href.includes(fragment))
}

export function FeedbackButton(): JSX.Element {
    const { realm } = useValues(preflightLogic)

    if (realm && realm === Realm.Cloud && !isOnPagesWithHighZIndex()) {
        return (
            <div
                data-attr="posthog-feedback-button"
                className="h-10 items-center cursor-pointer flex text-primary-alt font-semibold"
            >
                Feedback
            </div>
        )
    }
    return <></>
}
