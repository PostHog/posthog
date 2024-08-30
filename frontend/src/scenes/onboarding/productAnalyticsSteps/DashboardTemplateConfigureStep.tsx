import { IconArrowRight } from '@posthog/icons'
import { LemonButton, LemonCard, LemonSkeleton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import {
    appEditorUrl,
    authorizedUrlListLogic,
    AuthorizedUrlListType,
} from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { useRef, useState } from 'react'
import { DashboardTemplateVariables } from 'scenes/dashboard/DashboardTemplateVariables'
import { dashboardTemplateVariablesLogic } from 'scenes/dashboard/dashboardTemplateVariablesLogic'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'

import { OnboardingStepKey } from '../onboardingLogic'
import { OnboardingStep } from '../OnboardingStep'
import { sdksLogic } from '../sdks/sdksLogic'
import { onboardingTemplateConfigLogic } from './onboardingTemplateConfigLogic'

export const OnboardingDashboardTemplateConfigureStep = ({
    stepKey = OnboardingStepKey.DASHBOARD_TEMPLATE,
}: {
    stepKey?: OnboardingStepKey
}): JSX.Element => {
    const { activeDashboardTemplate, host } = useValues(onboardingTemplateConfigLogic)
    const { setHost } = useActions(onboardingTemplateConfigLogic)
    const { createDashboardFromTemplate } = useActions(newDashboardLogic)
    const { isLoading } = useValues(newDashboardLogic)
    const { variables } = useValues(dashboardTemplateVariablesLogic)
    const { snippetHosts } = useValues(sdksLogic)
    const { addUrl } = useActions(authorizedUrlListLogic({ actionId: null, type: AuthorizedUrlListType.TOOLBAR_URLS }))

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
                            {host ? (
                                <DashboardTemplateConfigIframe host={host} />
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
                                                                setHost(host)
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
                            <DashboardTemplateVariables />
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

const DashboardTemplateConfigIframe = ({ host }: { host: string }): JSX.Element => {
    const iframeRef = useRef<HTMLIFrameElement>(null)

    return (
        <div className="border border-1 border-border-bold p-2 rounded h-full w-full">
            <iframe
                ref={iframeRef}
                className="w-full h-full rounded"
                src={appEditorUrl(host, {
                    userIntent: 'add-action',
                })}
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    background: '#FFF',
                }}
                // onLoad={onIframeLoad}
                // these two sandbox values are necessary so that the site and toolbar can run
                // this is a very loose sandbox,
                // but we specify it so that at least other capabilities are denied
                sandbox="allow-scripts allow-same-origin"
                // we don't allow things such as camera access though
                allow=""
            />
        </div>
    )
}
