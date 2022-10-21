import { useValues } from 'kea'
import { LemonButton } from 'lib/components/LemonButton'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { Realm } from '~/types'

export function FeedbackButton(): JSX.Element {
    const { realm } = useValues(preflightLogic)

    if (realm && realm === Realm.Cloud) {
        return (
            <LemonButton data-attr="posthog-feedback-button">
                <span className="text-default grow" data-attr="posthog-feedback-button">
                    Feedback
                </span>
            </LemonButton>
        )
    }
    return <></>
}
