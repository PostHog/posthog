import { IconArrowRight } from '@posthog/icons'
import { LemonButton, LemonCard, LemonSkeleton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { authorizedUrlListLogic, AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { IframedToolbarBrowser } from 'lib/components/IframedToolbarBrowser/IframedToolbarBrowser'
import { iframedToolbarBrowserLogic } from 'lib/components/IframedToolbarBrowser/iframedToolbarBrowserLogic'
import { useRef, useState } from 'react'
import { dashboardTemplateVariablesLogic } from 'scenes/dashboard/dashboardTemplateVariablesLogic'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'

import { OnboardingStepKey } from '../onboardingLogic'
import { OnboardingStep } from '../OnboardingStep'
import { sdksLogic } from '../sdks/sdksLogic'
import { DashboardTemplateVariables } from './DashboardTemplateVariables'
import { onboardingTemplateConfigLogic } from './onboardingTemplateConfigLogic'

export const OnboardingDashboardTemplateConfigureStep = ({
    stepKey = OnboardingStepKey.DASHBOARD_TEMPLATE,
}: {
    stepKey?: OnboardingStepKey
}): JSX.Element => {
    const iframeRef = useRef<HTMLIFrameElement>(null)
    const { activeDashboardTemplate } = useValues(onboardingTemplateConfigLogic)
    const { createDashboardFromTemplate } = useActions(newDashboardLogic)
    const { isLoading } = useValues(newDashboardLogic)
    const { snippetHosts } = useValues(sdksLogic)
    const { addUrl } = useActions(authorizedUrlListLogic({ actionId: null, type: AuthorizedUrlListType.TOOLBAR_URLS }))
    const { setBrowserUrl } = useActions(iframedToolbarBrowserLogic({ iframeRef, clearBrowserUrlOnUnmount: true }))
    const { browserUrl } = useValues(iframedToolbarBrowserLogic({ iframeRef, clearBrowserUrlOnUnmount: true }))
    const theDashboardTemplateVariablesLogic = dashboardTemplateVariablesLogic({
        variables: activeDashboardTemplate?.variables || [],
    })
    const { variables, allVariablesAreTouched } = useValues(theDashboardTemplateVariablesLogic)

    const [isSubmitting, setIsSubmitting] = useState(false)

    return (
        <OnboardingStep
            title={activeDashboardTemplate?.template_name || 'Configure dashboard'}
            stepKey={stepKey}
            breadcrumbHighlightName={OnboardingStepKey.DASHBOARD_TEMPLATE}
            fullWidth
            continueOverride={<></>}
        >
            {isSubmitting || isLoading ? (
                <p>Creating dashboard...</p>
            ) : (
                <>
                    <div className="grid grid-cols-6 space-x-6 min-h-[80vh]">
                        <div className="col-span-4 relative">
                            {browserUrl ? (
                                <div className="border border-1 border-border-bold p-2 rounded h-full w-full">
                                    <IframedToolbarBrowser iframeRef={iframeRef} userIntent="add-action" />
                                </div>
                            ) : (
                                <>
                                    <div className="absolute inset-0 bg-primary-alt-highlight z-10 rounded opacity-80 backdrop-filter backdrop-blur-md flex items-center justify-center" />
                                    <div className="absolute inset-0 z-20 rounded flex items-center justify-center">
                                        <LemonCard className="max-w-lg" hoverEffect={false}>
                                            <h2>Select where you want to track events from.</h2>
                                            <p>
                                                Not seeing the site you want? Install posthog-js or the HTML snippet
                                                wherever you want to track events, then come back here.
                                            </p>
                                            {snippetHosts.length > 0 ? (
                                                <div className="space-y-2">
                                                    {snippetHosts.map((host) => (
                                                        <LemonButton
                                                            key={`snippet-host-button-${host}`}
                                                            type="tertiary"
                                                            status="default"
                                                            onClick={() => {
                                                                addUrl(host)
                                                                setBrowserUrl(host)
                                                            }}
                                                            sideIcon={<IconArrowRight />}
                                                        >
                                                            {host}
                                                        </LemonButton>
                                                    ))}
                                                </div>
                                            ) : (
                                                <p>
                                                    Hm, we're not finding any available hosts. Head back to the install
                                                    step to install posthog-js in your frontend.
                                                </p>
                                            )}
                                        </LemonCard>
                                    </div>
                                    <div className="space-y-6 relative m-6">
                                        <LemonSkeleton className="h-10 rounded-lg w-1/3" />
                                        <div className="space-y-2">
                                            <LemonSkeleton repeat={5} />
                                        </div>
                                        <div className="space-y-2">
                                            <LemonSkeleton repeat={3} />
                                        </div>
                                        <LemonSkeleton className="h-6 rounded-lg w-2/3" />
                                        <div className="space-y-2">
                                            <LemonSkeleton repeat={3} />
                                        </div>
                                        <LemonSkeleton className="h-10 rounded-lg w-2/3" />
                                        <div className="space-y-2">
                                            <LemonSkeleton repeat={5} />
                                        </div>
                                    </div>
                                </>
                            )}
                        </div>
                        <div className="col-span-2">
                            <p>
                                For each action below, select an element on your site that indicates when that action is
                                taken, or enter a custom event name that you'll send from your backend.
                            </p>
                            <DashboardTemplateVariables hasSelectedSite={!!browserUrl} />
                            <LemonButton
                                type="primary"
                                status="alt"
                                onClick={() => {
                                    if (activeDashboardTemplate) {
                                        setIsSubmitting(true)
                                        createDashboardFromTemplate(activeDashboardTemplate, variables, false)
                                    }
                                }}
                                loading={isLoading}
                                fullWidth
                                center
                                className="mt-6"
                                disabledReason={!allVariablesAreTouched && 'Please select an event for each variable'}
                            >
                                Create dashboard
                            </LemonButton>
                        </div>
                    </div>
                </>
            )}
        </OnboardingStep>
    )
}
