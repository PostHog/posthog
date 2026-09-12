import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType, authorizedUrlListLogic } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'

const AUTHORIZED_URL_LOGIC_PROPS = {
    actionId: null,
    experimentId: null,
    productTourId: null,
    type: AuthorizedUrlListType.WEB_ANALYTICS,
    allowWildCards: false,
} as const

/**
 * Goal-conditional step for `improve_experience`: web analytics breaks traffic down by authorized
 * URL, so the goal's finish line (a live dashboard) needs at least one. Wildcards are off - the
 * URL must be concrete so the toolbar and agents can open the site.
 */
export function AuthorizedUrlsStep({
    onContinue,
    onSkip,
}: {
    onContinue: () => void
    onSkip: () => void
}): JSX.Element {
    const logic = authorizedUrlListLogic(AUTHORIZED_URL_LOGIC_PROPS)
    const { authorizedUrls, editUrlIndex, proposedUrl, isProposedUrlSubmitting } = useValues(logic)
    const { newUrl } = useActions(logic)
    const [showRequirement, setShowRequirement] = useState(false)

    const handleContinue = async (): Promise<void> => {
        // Continue is the only commit path, so a URL still in the form, new or edited, is saved before the
        // step moves on. A submit that fails validation keeps the form open with the reason.
        if (editUrlIndex !== null && proposedUrl.url) {
            await logic.asyncActions.submitProposedUrl()
            if (logic.values.editUrlIndex !== null) {
                return
            }
        }
        if (logic.values.authorizedUrls.length === 0) {
            setShowRequirement(true)
            if (logic.values.editUrlIndex === null) {
                newUrl()
            }
            return
        }
        onContinue()
    }

    return (
        <div className="flex flex-col gap-5">
            <p className="text-secondary text-center m-0">
                Add each full URL where your site runs. Web analytics needs at least one URL to show where your traffic
                comes from.
            </p>
            <LemonBanner type="info">Include https:// in each URL. Wildcards are not supported.</LemonBanner>
            <AuthorizedUrlList
                type={AuthorizedUrlListType.WEB_ANALYTICS}
                allowWildCards={false}
                hideEmptyState
                hideAddFormSubmit
                showLaunch={false}
            />
            <div className="flex flex-col items-center gap-1 pt-2">
                {showRequirement && authorizedUrls.length === 0 && (
                    <p className="text-danger text-center m-0">
                        Add one URL to continue, or skip for now and add it later in settings.
                    </p>
                )}
                <LemonButton
                    type="primary"
                    status="alt"
                    onClick={() => void handleContinue()}
                    loading={isProposedUrlSubmitting}
                    data-attr="onboarding-authorized-urls-continue"
                >
                    Continue
                </LemonButton>
                <LemonButton type="tertiary" size="small" onClick={onSkip}>
                    Skip for now
                </LemonButton>
            </div>
        </div>
    )
}
