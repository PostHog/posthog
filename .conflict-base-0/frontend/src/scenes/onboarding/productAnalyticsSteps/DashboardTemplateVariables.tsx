import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconCheckCircle, IconInfo, IconTarget, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCollapse, LemonInput, LemonLabel, LemonMenu, Spinner } from '@posthog/lemon-ui'

import { iframedToolbarBrowserLogic } from 'lib/components/IframedToolbarBrowser/iframedToolbarBrowserLogic'
import { dashboardTemplateVariablesLogic } from 'scenes/dashboard/dashboardTemplateVariablesLogic'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'

import { DashboardTemplateVariableType, EntityTypes } from '~/types'

import { onboardingTemplateConfigLogic } from './onboardingTemplateConfigLogic'

function VariableSelector({
    variableName,
    hasSelectedSite,
    iframeRef,
}: {
    variableName: string
    hasSelectedSite: boolean
    iframeRef: React.RefObject<HTMLIFrameElement>
}): JSX.Element {
    const { activeDashboardTemplate } = useValues(newDashboardLogic)
    const theDashboardTemplateVariablesLogic = dashboardTemplateVariablesLogic({
        variables: activeDashboardTemplate?.variables || [],
    })
    const {
        setVariable,
        setVariableForPageview,
        setVariableForScreenview,
        resetVariable,
        goToNextUntouchedActiveVariableIndex,
        incrementActiveVariableIndex,
        setIsCurrentlySelectingElement,
        setActiveVariableCustomEventName,
    } = useActions(theDashboardTemplateVariablesLogic)
    const {
        allVariablesAreTouched,
        variables,
        activeVariableIndex,
        isCurrentlySelectingElement,
        activeVariableCustomEventName,
    } = useValues(theDashboardTemplateVariablesLogic)
    const { customEventFieldShown } = useValues(onboardingTemplateConfigLogic)
    const { showCustomEventField, hideCustomEventField } = useActions(onboardingTemplateConfigLogic)
    const { enableElementSelector, disableElementSelector, setNewActionName } = useActions(
        iframedToolbarBrowserLogic({ iframeRef, clearBrowserUrlOnUnmount: true })
    )
    const { currentFullUrl, browserUrl, currentPath } = useValues(
        iframedToolbarBrowserLogic({ iframeRef, clearBrowserUrlOnUnmount: true })
    )

    const variable: DashboardTemplateVariableType | undefined = variables.find((v) => v.name === variableName)
    if (!variable) {
        return <></>
    }

    return (
        <div className="pl-7">
            <div className="mb-2">
                <p>
                    <IconInfo /> {variable.description}
                </p>
            </div>
            {!customEventFieldShown && activeVariableIndex == 0 && hasSelectedSite && !variable.touched && (
                <LemonBanner type="info" className="mb-4">
                    <p>
                        <strong>Tip:</strong> Navigate to the page you want before you start selecting.
                    </p>
                </LemonBanner>
            )}
            {variable.touched && !activeVariableCustomEventName && (
                <div className="flex justify-between items-center bg-primary-light p-2 pl-3 rounded mb-4">
                    <div>
                        <p className="mb-2">
                            <IconCheckCircle className="text-success font-bold" />{' '}
                            <span className="text-success font-bold">Selected</span>
                        </p>
                        <div className="ml-4">
                            {variable.default.type === EntityTypes.ACTIONS ? (
                                <>
                                    <p className="text-secondary mb-0 text-xs">
                                        <span className="font-bold">CSS selector:</span>{' '}
                                        {variable.default.selector || 'not set'}
                                    </p>
                                    <p className="text-secondary mb-0 text-xs">
                                        <span className="font-bold">Element href:</span>{' '}
                                        {variable.default.href || 'not set'}
                                    </p>
                                    <p className="text-secondary mb-1 text-xs">
                                        <span className="font-bold">Page URL:</span> {variable.default.url || 'any url'}
                                    </p>
                                </>
                            ) : variable.default.type === EntityTypes.EVENTS &&
                              variable.default.name == '$screenview' ? (
                                <p className="text-secondary mb-1 text-xs">
                                    <span className="font-bold">Screenview:</span>{' '}
                                    {variable.default.properties?.[0].value || 'any screenview'}
                                </p>
                            ) : variable.default.type === EntityTypes.EVENTS ? (
                                <p className="text-secondary mb-1 text-xs">
                                    <span className="font-bold">Pageview URL contains:</span>{' '}
                                    {variable.default.properties?.[0].value || 'any url'}
                                </p>
                            ) : null}
                        </div>
                    </div>
                    <div>
                        <LemonButton
                            icon={<IconTrash />}
                            type="tertiary"
                            size="small"
                            onClick={() => resetVariable(variable.id)}
                        />
                    </div>
                </div>
            )}
            {customEventFieldShown && (
                <div className="mb-4">
                    <LemonLabel>Custom event name</LemonLabel>
                    <p>
                        Set the name that you'll use for a custom event (eg. a backend event) instead of selecting an
                        event from your site. You can change this later if needed.
                    </p>
                    <div className="flex gap-x-2 w-full">
                        <LemonInput
                            className="grow"
                            value={activeVariableCustomEventName || ''}
                            onChange={(v) => {
                                if (v) {
                                    setActiveVariableCustomEventName(v)
                                    setVariable(variable.name, {
                                        events: [{ id: v, math: 'dau', type: 'events', custom_event: true }],
                                    })
                                } else {
                                    setActiveVariableCustomEventName(null)
                                    resetVariable(variable.id)
                                }
                            }}
                            onBlur={() => {
                                if (activeVariableCustomEventName) {
                                    setVariable(variable.name, {
                                        events: [
                                            {
                                                id: activeVariableCustomEventName,
                                                math: 'dau',
                                                type: 'events',
                                                custom_event: true,
                                            },
                                        ],
                                    })
                                } else {
                                    resetVariable(variable.id)
                                    hideCustomEventField()
                                }
                            }}
                        />
                        <div>
                            <LemonButton
                                icon={<IconTrash />}
                                type="tertiary"
                                size="small"
                                onClick={() => {
                                    disableElementSelector()
                                    setNewActionName(null)
                                    resetVariable(variable.id)
                                    setActiveVariableCustomEventName(null)
                                    hideCustomEventField()
                                }}
                            />
                        </div>
                    </div>
                </div>
            )}

            <div className="flex">
                {variable.touched ? (
                    <>
                        {!allVariablesAreTouched ||
                        (allVariablesAreTouched && variables.length !== activeVariableIndex + 1) ? (
                            <LemonButton
                                type="primary"
                                status="alt"
                                onClick={() => {
                                    customEventFieldShown && hideCustomEventField()
                                    allVariablesAreTouched
                                        ? goToNextUntouchedActiveVariableIndex()
                                        : variables.length !== activeVariableIndex + 1
                                          ? incrementActiveVariableIndex()
                                          : null
                                }}
                            >
                                Continue
                            </LemonButton>
                        ) : null}
                    </>
                ) : (
                    <div className="w-full flex flex-wrap gap-x-2 gap-y-2">
                        {isCurrentlySelectingElement ? (
                            <LemonButton
                                type="secondary"
                                onClick={() => {
                                    disableElementSelector()
                                    setNewActionName(null)
                                    setIsCurrentlySelectingElement(false)
                                }}
                                icon={<Spinner textColored className="text-secondary" />}
                                center
                                className="min-w-44"
                            >
                                Cancel selection
                            </LemonButton>
                        ) : (
                            <LemonButton
                                type="primary"
                                status="alt"
                                onClick={() => {
                                    hideCustomEventField()
                                    enableElementSelector()
                                    setNewActionName(variable.name)
                                    setIsCurrentlySelectingElement(true)
                                }}
                                icon={<IconTarget />}
                                center
                                className="min-w-44"
                                disabledReason={!hasSelectedSite && 'Please select a site to continue'}
                            >
                                Select from site
                            </LemonButton>
                        )}
                        <LemonMenu
                            items={[
                                {
                                    title: 'Use pageview',
                                    items: [
                                        {
                                            label: (
                                                <div className="flex">
                                                    This pageview{' '}
                                                    {currentFullUrl ? (
                                                        <div className="text-secondary max-w-44 overflow-clip overflow-ellipsis text-nowrap ml-2">
                                                            {!currentPath ? browserUrl : '/' + currentPath}
                                                        </div>
                                                    ) : null}
                                                </div>
                                            ),
                                            onClick: () => setVariableForPageview(variable.name, currentFullUrl || ''),
                                            disabledReason: !currentFullUrl
                                                ? 'Please select a site to use a specific pageview'
                                                : undefined,
                                        },
                                        {
                                            label: 'Any pageview',
                                            onClick: () => setVariableForPageview(variable.name, browserUrl || ''),
                                        },
                                        {
                                            label: 'Any screenview (mobile apps)',
                                            onClick: () => setVariableForScreenview(variable.name),
                                        },
                                    ],
                                },
                            ]}
                        >
                            <LemonButton type="secondary">Use pageview</LemonButton>
                        </LemonMenu>
                        <LemonButton
                            type="secondary"
                            onClick={() => {
                                disableElementSelector()
                                setNewActionName(null)
                                showCustomEventField()
                                setIsCurrentlySelectingElement(false)
                            }}
                            fullWidth
                            center
                            className="grow max-w-44"
                        >
                            Use custom event
                        </LemonButton>
                    </div>
                )}
            </div>
        </div>
    )
}

export function DashboardTemplateVariables({
    hasSelectedSite,
    iframeRef,
}: {
    hasSelectedSite: boolean
    iframeRef: React.RefObject<HTMLIFrameElement>
}): JSX.Element {
    const { activeDashboardTemplate } = useValues(newDashboardLogic)
    const theDashboardTemplateVariablesLogic = dashboardTemplateVariablesLogic({
        variables: activeDashboardTemplate?.variables || [],
    })
    const { variables, activeVariableIndex } = useValues(theDashboardTemplateVariablesLogic)
    const { setVariables, setActiveVariableIndex, setIsCurrentlySelectingElement } = useActions(
        theDashboardTemplateVariablesLogic
    )
    const { setNewActionName, disableElementSelector } = useActions(
        iframedToolbarBrowserLogic({ iframeRef, clearBrowserUrlOnUnmount: true })
    )

    // TODO: onboarding-dashboard-templates: this is a hack, I'm not sure why it's not set properly initially.
    useEffect(() => {
        setVariables(activeDashboardTemplate?.variables || [])
    }, [activeDashboardTemplate]) // oxlint-disable-line react-hooks/exhaustive-deps

    return (
        <div className="mb-4 DashboardTemplateVariables max-w-192">
            <LemonCollapse
                activeKey={variables[activeVariableIndex]?.id}
                panels={variables.map((v, i) => ({
                    key: v.id,
                    header: (
                        <div>
                            {v.name}
                            {v.touched && <IconCheckCircle className="text-success ml-2 text-base" />}
                        </div>
                    ),
                    content: (
                        <VariableSelector
                            variableName={v.name}
                            {...v}
                            hasSelectedSite={hasSelectedSite}
                            iframeRef={iframeRef}
                        />
                    ),
                    className: 'p-4 bg-primary',
                    onHeaderClick: () => {
                        setActiveVariableIndex(i)
                        disableElementSelector()
                        setNewActionName(null)
                        setIsCurrentlySelectingElement(false)
                    },
                }))}
                embedded
                size="small"
            />
        </div>
    )
}
