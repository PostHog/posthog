import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconArrowRight, IconCheckCircle } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCard,
    LemonInput,
    LemonInputSelect,
    LemonSkeleton,
    Link,
    Spinner,
} from '@posthog/lemon-ui'

import {
    AuthorizedUrlListType,
    authorizedUrlListLogic,
    defaultAuthorizedUrlProperties,
} from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { IframedToolbarBrowser } from 'lib/components/IframedToolbarBrowser/IframedToolbarBrowser'
import { iframedToolbarBrowserLogic } from 'lib/components/IframedToolbarBrowser/iframedToolbarBrowserLogic'
import { StarHog } from 'lib/components/hedgehogs'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { dashboardTemplateVariablesLogic } from 'scenes/dashboard/dashboardTemplateVariablesLogic'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'

import { OnboardingStepKey } from '~/types'

import { OnboardingStep } from '../OnboardingStep'
import { onboardingLogic } from '../onboardingLogic'
import { sdksLogic } from '../sdks/sdksLogic'
import { DashboardTemplateVariables } from './DashboardTemplateVariables'
import { onboardingTemplateConfigLogic } from './onboardingTemplateConfigLogic'

const UrlInput = ({ iframeRef }: { iframeRef: React.RefObject<HTMLIFrameElement> }): JSX.Element => {
    const { setBrowserUrl, setInitialPath } = useActions(
        iframedToolbarBrowserLogic({ iframeRef, clearBrowserUrlOnUnmount: true })
    )
    const { browserUrl, currentPath } = useValues(
        iframedToolbarBrowserLogic({ iframeRef, clearBrowserUrlOnUnmount: true })
    )
    const { combinedSnippetAndLiveEventsHosts } = useValues(sdksLogic)
    const { addUrl } = useActions(
        authorizedUrlListLogic({
            ...defaultAuthorizedUrlProperties,
            type: AuthorizedUrlListType.TOOLBAR_URLS,
        })
    )
    const [inputValue, setInputValue] = useState(currentPath)

    useEffect(() => {
        setInputValue(currentPath)
    }, [currentPath])

    return (
        <div className="border-1 border-primary flex w-full gap-x-2 border-b p-2">
            <LemonInput
                size="medium"
                className="grow pl-0.5 font-mono text-sm"
                defaultValue={currentPath}
                value={inputValue}
                onChange={(v) => setInputValue(v)}
                onPressEnter={() => {
                    setInitialPath(inputValue || '')
                }}
                prefix={
                    <span className="-mr-2 flex items-center">
                        <div className="bg-primary rounded">
                            <LemonInputSelect
                                mode="single"
                                value={[browserUrl || 'my-website.com']}
                                options={combinedSnippetAndLiveEventsHosts.map((host) => ({ key: host, label: host }))}
                                allowCustomValues={false}
                                onChange={(v) => {
                                    addUrl(v[0])
                                    setBrowserUrl(v[0])
                                    setInitialPath('')
                                }}
                                size="xsmall"
                                transparentBackground
                                className="border-none"
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
        </div>
    )
}

export const SiteChooser = (): JSX.Element => {
    const iframeRef = useRef<HTMLIFrameElement>(null)
    const { combinedSnippetAndLiveEventsHosts, hasSnippetEventsLoading } = useValues(sdksLogic)
    const { setStepKey } = useActions(onboardingLogic)
    const { isCloud } = useValues(preflightLogic)
    const { setProposedBrowserUrl } = useActions(
        iframedToolbarBrowserLogic({
            iframeRef,
            clearBrowserUrlOnUnmount: true,
            automaticallyAuthorizeBrowserUrl: true,
        })
    )
    const { iframeBanner, proposedBrowserUrl } = useValues(
        iframedToolbarBrowserLogic({
            iframeRef,
            clearBrowserUrlOnUnmount: true,
            automaticallyAuthorizeBrowserUrl: true,
        })
    )

    return (
        <>
            <div className="bg-primary-alt-highlight absolute inset-0 z-10 flex items-center justify-center rounded opacity-80 backdrop-blur-md backdrop-filter" />
            <div className="absolute inset-0 z-20 flex items-center justify-center rounded">
                <LemonCard className="max-w-lg" hoverEffect={false}>
                    {iframeBanner?.level == 'error' && (
                        <LemonBanner type="error" className="mb-4">
                            <p className="font-bold">
                                Your site failed to load in the iFrame. It's possible your site doesn't allow iFrames.
                            </p>
                            <p>
                                We're working on a way to do this without iFrames. Until then, you can use another site,
                                or set custom event names for your dashboard.
                            </p>
                        </LemonBanner>
                    )}
                    <h2>Select where you want to track events from.</h2>
                    {hasSnippetEventsLoading ? (
                        <Spinner />
                    ) : combinedSnippetAndLiveEventsHosts.length > 0 ? (
                        <>
                            <p>
                                Not seeing the site you want? Try clicking around on your site to trigger a few events.
                                If you haven't yet,{' '}
                                <Link onClick={() => setStepKey(OnboardingStepKey.INSTALL)}>install posthog-js</Link> or
                                the HTML snippet wherever you want to track events, then come back here.
                            </p>
                            {isCloud && (
                                <p className="text-secondary italic">
                                    Note: Sites must be served over HTTPS to be selected.
                                </p>
                            )}
                            <div className="deprecated-space-y-2">
                                {combinedSnippetAndLiveEventsHosts.map((host) => (
                                    <LemonButton
                                        key={`snippet-host-button-${host}`}
                                        type="tertiary"
                                        status="default"
                                        onClick={() => {
                                            setProposedBrowserUrl(host)
                                        }}
                                        sideIcon={<IconArrowRight />}
                                        disabledReason={proposedBrowserUrl && 'Loading...'}
                                    >
                                        {host}
                                    </LemonButton>
                                ))}
                            </div>
                        </>
                    ) : (
                        <>
                            <p className="text-secondary">
                                Hm, it looks like you haven't ingested any events from a website yet. To select actions
                                from your site, head back to the{' '}
                                <Link onClick={() => setStepKey(OnboardingStepKey.INSTALL)}>install step</Link> to
                                install posthog-js in your frontend.
                            </p>
                            <p className="text-secondary">
                                You can still create a dashboard using custom event names, though it's not quite as fun.
                            </p>
                            <LemonButton onClick={() => setStepKey(OnboardingStepKey.INSTALL)} type="primary">
                                Install posthog-js
                            </LemonButton>
                        </>
                    )}
                </LemonCard>
            </div>
            <div className="deprecated-space-y-6 relative m-6">
                <LemonSkeleton className="h-10 w-1/3 rounded-lg" />
                <div className="deprecated-space-y-2">
                    <LemonSkeleton repeat={5} />
                </div>
                <div className="deprecated-space-y-2">
                    <LemonSkeleton repeat={3} />
                </div>
                <LemonSkeleton className="h-6 w-2/3 rounded-lg" />
                <div className="deprecated-space-y-2">
                    <LemonSkeleton repeat={3} />
                </div>
                <LemonSkeleton className="h-10 w-2/3 rounded-lg" />
                <div className="deprecated-space-y-2">
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
    const { browserUrl, iframeBanner } = useValues(
        iframedToolbarBrowserLogic({ iframeRef, clearBrowserUrlOnUnmount: true })
    )
    const theDashboardTemplateVariablesLogic = dashboardTemplateVariablesLogic({
        variables: activeDashboardTemplate?.variables || [],
    })
    const { variables, allVariablesAreTouched, hasTouchedAnyVariable } = useValues(theDashboardTemplateVariablesLogic)
    const { goToNextStep } = useActions(onboardingLogic)

    const { dashboardCreatedDuringOnboarding } = useValues(onboardingTemplateConfigLogic)

    return (
        <OnboardingStep
            title={activeDashboardTemplate?.template_name || 'Configure dashboard'}
            stepKey={stepKey}
            breadcrumbHighlightName={OnboardingStepKey.DASHBOARD_TEMPLATE}
            fullWidth
            continueOverride={<></>}
        >
            <>
                {dashboardCreatedDuringOnboarding ? (
                    <div className="mx-auto mb-8 max-w-screen-md">
                        <div className="bg-success-highlight flex items-center justify-between rounded p-6">
                            <div className="flex gap-x-4">
                                <IconCheckCircle className="text-success mb-6 text-3xl" />
                                <div>
                                    <h3 className="mb-1 text-left text-lg font-bold">Dashboard created!</h3>
                                    <p className="mx-0 mb-0">We'll take you there when you're done onboarding.</p>
                                </div>
                            </div>
                            <div className="h-20">
                                <StarHog className="h-full w-full" />
                            </div>
                        </div>
                        <div className="flex w-full justify-end">
                            <LemonButton
                                type="primary"
                                status="alt"
                                data-attr="show-plans"
                                className="mt-4"
                                onClick={() => goToNextStep()}
                                icon={<IconArrowRight />}
                            >
                                Continue
                            </LemonButton>
                        </div>
                    </div>
                ) : (
                    <div className="deprecated-space-x-6 grid min-h-[80vh] grid-cols-6">
                        <div className="relative col-span-4 max-h-[100vh] overflow-y-hidden">
                            {browserUrl && iframeBanner?.level != 'error' ? (
                                <div className="border-1 border-primary flex h-full w-full flex-col rounded border">
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
                            <p className="italic">PS! These don't have to be perfect, you can fine-tune them later.</p>
                            <DashboardTemplateVariables hasSelectedSite={!!browserUrl} iframeRef={iframeRef} />
                            <div className="mt-6 flex w-full flex-wrap justify-center gap-x-2 gap-y-2">
                                <div className="min-w-64 grow">
                                    <LemonButton
                                        type="primary"
                                        status="alt"
                                        onClick={() => {
                                            if (activeDashboardTemplate) {
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
                                    {/* )} */}
                                </div>
                                <div className="max-w-56">
                                    <LemonButton
                                        type="tertiary"
                                        onClick={() => goToNextStep()}
                                        fullWidth
                                        center
                                        disabledReason={
                                            isLoading
                                                ? 'Dashboard creating...'
                                                : dashboardCreatedDuringOnboarding
                                                  ? 'Dashboard already created'
                                                  : undefined
                                        }
                                    >
                                        {hasTouchedAnyVariable ? 'Discard dashboard & skip' : 'Skip for now'}
                                    </LemonButton>
                                </div>
                            </div>
                        </div>
                    </div>
                )}
            </>
        </OnboardingStep>
    )
}
