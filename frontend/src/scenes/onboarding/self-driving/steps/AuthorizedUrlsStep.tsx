import { useValues } from 'kea'

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
    const { authorizedUrls } = useValues(authorizedUrlListLogic(AUTHORIZED_URL_LOGIC_PROPS))

    return (
        <div className="flex flex-col gap-5">
            <p className="text-secondary text-center m-0">
                Add each full URL where your site runs. Web analytics uses these URLs to show where your traffic comes
                from.
            </p>
            <LemonBanner type="info">Include https:// in each URL. Wildcards are not supported.</LemonBanner>
            <AuthorizedUrlList
                type={AuthorizedUrlListType.WEB_ANALYTICS}
                allowWildCards={false}
                hideEmptyState
                showLaunch={false}
            />
            <div className="flex flex-col items-center gap-1 pt-2">
                <LemonButton
                    type="primary"
                    status="alt"
                    onClick={onContinue}
                    disabledReason={authorizedUrls.length === 0 ? 'Add at least one URL' : null}
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
