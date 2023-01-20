import { useValues } from 'kea'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { Realm } from '~/types'
import './FeedbackButton.scss'

export function FeedbackButton(): JSX.Element {
    const { realm } = useValues(preflightLogic)

    if (realm && realm === Realm.Cloud) {
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
