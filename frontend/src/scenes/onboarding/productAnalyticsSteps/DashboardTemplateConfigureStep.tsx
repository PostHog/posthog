import { IconArrowRight } from '@posthog/icons'
import { LemonButton, LemonCard, LemonInput, LemonInputSelect, LemonSkeleton, Link, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { authorizedUrlListLogic, AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { IframedToolbarBrowser } from 'lib/components/IframedToolbarBrowser/IframedToolbarBrowser'
import { iframedToolbarBrowserLogic } from 'lib/components/IframedToolbarBrowser/iframedToolbarBrowserLogic'
import { useEffect, useRef, useState } from 'react'
import { dashboardTemplateVariablesLogic } from 'scenes/dashboard/dashboardTemplateVariablesLogic'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'

import { onboardingLogic, OnboardingStepKey } from '../onboardingLogic'
import { OnboardingStep } from '../OnboardingStep'
import { sdksLogic } from '../sdks/sdksLogic'
import { DashboardTemplateVariables } from './DashboardTemplateVariables'
import { onboardingTemplateConfigLogic } from './onboardingTemplateConfigLogic'

const UrlInput = ({ iframeRef }: { iframeRef: React.RefObject<HTMLIFrameElement> }): JSX.Element => {
    const { setBrowserUrl, setInitialPath } = useActions(
        iframedToolbarBrowserLogic({ iframeRef, clearBrowserUrlOnUnmount: true })
    )
    const { browserUrl, currentPath, currentFullUrl } = useValues(
        iframedToolbarBrowserLogic({ iframeRef, clearBrowserUrlOnUnmount: true })
    )
    const { snippetHosts } = useValues(sdksLogic)
    const { addUrl } = useActions(authorizedUrlListLogic({ actionId: null, type: AuthorizedUrlListType.TOOLBAR_URLS }))
    const [inputValue, setInputValue] = useState(currentPath)
    const { activeDashboardTemplate } = useValues(newDashboardLogic)
    const theDashboardTemplateVariablesLogic = dashboardTemplateVariablesLogic({
        variables: activeDashboardTemplate?.variables || [],
    })
    const { setVariableForPageview } = useActions(theDashboardTemplateVariablesLogic)
    const { activeVariable } = useValues(theDashboardTemplateVariablesLogic)

    useEffect(() => {
        setInputValue(currentPath)
    }, [currentPath])

    return (
        <div className="w-full flex gap-x-2 border-b border-1 border-border-bold p-2">
            <LemonInput
                size="small"
                className="grow font-mono text-sm"
                defaultValue={currentPath}
                value={inputValue}
                onChange={(v) => setInputValue(v)}
                onPressEnter={() => {
                    setInitialPath(inputValue || '')
                }}
                prefix={
                    <span className="-mr-2 flex items-center">
                        <div className="bg-bg-3000 rounded">
                            <LemonInputSelect
                                mode="single"
                                value={[browserUrl || 'my-website.com']}
                                options={snippetHosts.map((host) => ({ key: host, label: host }))}
                                allowCustomValues={false}
                                onChange={(v) => {
                                    addUrl(v[0])
                                    setBrowserUrl(v[0])
                                    setInitialPath('')
                                }}
                                size="xsmall"
                                transparentBackground
                                borderless
                            />
                        </div>
                        /
                    </span>
                }
            />
            <LemonButton
                size="small"
                type="primary"
                icon={<IconArrowRight />}
                onClick={() => {
                    setInitialPath(inputValue || '')
                }}
            />
            <LemonButton
                size="small"
                type="primary"
                status="alt"
                onClick={() => setVariableForPageview(activeVariable.name, currentFullUrl)}
            >
                Select pageview
            </LemonButton>
        </div>
    )
}

export const SiteChooser = (): JSX.Element => {
    const iframeRef = useRef<HTMLIFrameElement>(null)
    const { snippetHosts, hasSnippetEventsLoading } = useValues(sdksLogic)
    const { addUrl } = useActions(authorizedUrlListLogic({ actionId: null, type: AuthorizedUrlListType.TOOLBAR_URLS }))
    const { setBrowserUrl } = useActions(iframedToolbarBrowserLogic({ iframeRef, clearBrowserUrlOnUnmount: true }))
    const { setStepKey } = useActions(onboardingLogic)

    return (
        <>
            <div className="absolute inset-0 bg-primary-alt-highlight z-10 rounded opacity-80 backdrop-filter backdrop-blur-md flex items-center justify-center" />
            <div className="absolute inset-0 z-20 rounded flex items-center justify-center">
                <LemonCard className="max-w-lg" hoverEffect={false}>
                    <h2>Select where you want to track events from.</h2>
                    {hasSnippetEventsLoading ? (
                        <Spinner />
                    ) : snippetHosts.length > 0 ? (
                        <>
                            <p>
                                Not seeing the site you want? Install posthog-js or the HTML snippet wherever you want
                                to track events, then come back here.
                            </p>
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
                        </>
                    ) : (
                        <>
                            <p className="text-muted">
                                Hm, it looks like you haven't ingested any events from a website yet. To select actions
                                from your site, head back to the{' '}
                                <Link onClick={() => setStepKey(OnboardingStepKey.INSTALL)}>install step</Link> to
                                install posthog-js in your frontend.
                            </p>
                            <p className="text-muted">
                                You can still create a dashboard using custom event names, though it's not quite as fun.
                            </p>
                            <LemonButton onClick={() => setStepKey(OnboardingStepKey.INSTALL)} type="primary">
                                Install posthog-js
                            </LemonButton>
                        </>
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
    )
}

export const OnboardingDashboardTemplateConfigureStep = ({
    stepKey = OnboardingStepKey.DASHBOARD_TEMPLATE,
}: {
    stepKey?: OnboardingStepKey
}): JSX.Element => {
    const iframeRef = useRef<HTMLIFrameElement>(null)
    const { activeDashboardTemplate } = useValues(onboardingTemplateConfigLogic)
    const { createDashboardFromTemplate } = useActions(newDashboardLogic)
    const { isLoading } = useValues(newDashboardLogic)
    const { browserUrl } = useValues(iframedToolbarBrowserLogic({ iframeRef, clearBrowserUrlOnUnmount: true }))
    const theDashboardTemplateVariablesLogic = dashboardTemplateVariablesLogic({
        variables: activeDashboardTemplate?.variables || [],
    })
    const { variables, allVariablesAreTouched, hasTouchedAnyVariable } = useValues(theDashboardTemplateVariablesLogic)
    const { goToNextStep } = useActions(onboardingLogic)

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
                                <div className="border border-1 border-border-bold rounded h-full w-full flex flex-col">
                                    <UrlInput iframeRef={iframeRef} />
                                    <div className="m-2 grow rounded">
                                        <IframedToolbarBrowser iframeRef={iframeRef} userIntent="add-action" />
                                    </div>
                                </div>
                            ) : (
                                <SiteChooser />
                            )}
                        </div>
                        <div className="col-span-2">
                            <p>
                                For each action below, select an element on your site that indicates when that action is
                                taken, or enter a custom event name that you'll send using{' '}
                                <Link to="https://posthog.com/docs/product-analytics/capture-events">
                                    <code>posthog.capture()</code>
                                </Link>{' '}
                                (no need to send it now) .
                            </p>
                            <DashboardTemplateVariables hasSelectedSite={!!browserUrl} iframeRef={iframeRef} />
                            <div className="flex flex-wrap mt-6 w-full gap-x-2 gap-y-2 justify-center">
                                <div className="grow min-w-64">
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
                                        className="grow"
                                        disabledReason={
                                            !allVariablesAreTouched && 'Please select an event for each variable'
                                        }
                                    >
                                        Create dashboard
                                    </LemonButton>
                                </div>
                                <div className="max-w-56">
                                    <LemonButton type="tertiary" onClick={() => goToNextStep()} fullWidth center>
                                        {hasTouchedAnyVariable ? 'Discard dashboard & skip' : 'Skip for now'}
                                    </LemonButton>
                                </div>
                            </div>
                        </div>
                    </div>
                </>
            )}
        </OnboardingStep>
    )
}
