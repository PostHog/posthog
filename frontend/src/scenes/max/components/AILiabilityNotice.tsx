import { useActions, useValues } from 'kea'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

import { maxGlobalLogic } from '../maxGlobalLogic'

export function AILiabilityNotice(): JSX.Element | null {
    const { shouldShowLiabilityNotice } = useValues(maxGlobalLogic)
    const { dismissLiabilityNotice } = useActions(maxGlobalLogic)
    const { isAdminOrOwner } = useValues(organizationLogic)

    if (!shouldShowLiabilityNotice) {
        return null
    }

    return (
        <div className="flex flex-col mb-2 max-w-160 w-full px-3">
            <LemonBanner type="ai" onClose={dismissLiabilityNotice}>
                PostHog AI uses third-party LLM providers (OpenAI and Anthropic). Your data will not be used for
                training models.
                {isAdminOrOwner && (
                    <>
                        {' '}
                        If you'd rather disable this feature,{' '}
                        <Link to={urls.settings('organization-details', 'organization-ai-consent')}>
                            manage AI settings
                        </Link>
                        .
                    </>
                )}{' '}
                <Link to="https://posthog.com/docs/posthog-ai/faq" target="_blank" disableDocsPanel>
                    Learn more
                </Link>
            </LemonBanner>
        </div>
    )
}
