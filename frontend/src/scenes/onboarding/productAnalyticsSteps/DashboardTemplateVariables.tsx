import { IconCheckCircle, IconInfo, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCollapse, LemonInput, LemonLabel } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'
import { dashboardTemplateVariablesLogic } from 'scenes/dashboard/dashboardTemplateVariablesLogic'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'

import { DashboardTemplateVariableType } from '~/types'

function VariableSelector({
    variable,
    hasSelectedSite,
}: {
    variable: DashboardTemplateVariableType
    hasSelectedSite: boolean
}): JSX.Element {
    const { activeDashboardTemplate } = useValues(newDashboardLogic)
    const theDashboardTemplateVariablesLogic = dashboardTemplateVariablesLogic({
        variables: activeDashboardTemplate?.variables || [],
    })
    const { setVariable, resetVariable, goToNextUntouchedActiveVariableIndex, incrementActiveVariableIndex } =
        useActions(theDashboardTemplateVariablesLogic)
    const { allVariablesAreTouched, variables, activeVariableIndex } = useValues(theDashboardTemplateVariablesLogic)
    const [customEventName, setCustomEventName] = useState<string | null>(null)
    const [showCustomEventField, setShowCustomEventField] = useState(false)

    const FALLBACK_EVENT = {
        id: '$other_event',
        math: 'dau',
        type: 'events',
    }

    return (
        <div className="pl-7">
            <div className="mb-2">
                <p>
                    <IconInfo /> {variable.description}
                </p>
            </div>
            {variable.touched && !customEventName && (
                <div className="flex justify-between items-center bg-bg-3000-light p-2 pl-3 rounded mb-4">
                    <div>
                        <IconCheckCircle className="text-success font-bold" />{' '}
                        <span className="text-success font-bold">Selected</span>
                        <p className="italic text-muted mb-0">.md-invite-button</p>
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
            {showCustomEventField && (
                <div className="mb-4">
                    <LemonLabel>Custom event name</LemonLabel>
                    <p>
                        Set the name that you'll use for a custom event (eg. a backend event) instead of selecting an
                        event from your site. You can change this later if needed.
                    </p>
                    <div className="flex gap-x-2 w-full">
                        <LemonInput
                            className="grow"
                            onChange={(v) => {
                                if (v) {
                                    setCustomEventName(v)
                                    setVariable(variable.name, {
                                        events: [{ id: v, math: 'dau', type: 'events' }],
                                    })
                                } else {
                                    setCustomEventName(null)
                                    resetVariable(variable.id)
                                }
                            }}
                            onBlur={() => {
                                if (customEventName) {
                                    setVariable(variable.name, {
                                        events: [{ id: customEventName, math: 'dau', type: 'events' }],
                                    })
                                } else {
                                    resetVariable(variable.id)
                                    setShowCustomEventField(false)
                                }
                            }}
                        />
                        <div>
                            <LemonButton
                                icon={<IconTrash />}
                                type="tertiary"
                                size="small"
                                onClick={() => {
                                    resetVariable(variable.id)
                                    setCustomEventName(null)
                                    setShowCustomEventField(false)
                                }}
                            />
                        </div>
                    </div>
                </div>
            )}
            {!hasSelectedSite ? (
                <LemonBanner type="warning">Please select a site to continue. </LemonBanner>
            ) : (
                <div className="flex">
                    {variable.touched ? (
                        <>
                            {!allVariablesAreTouched ||
                            (allVariablesAreTouched && variables.length !== activeVariableIndex + 1) ? (
                                <LemonButton
                                    type="primary"
                                    status="alt"
                                    onClick={() =>
                                        !allVariablesAreTouched
                                            ? goToNextUntouchedActiveVariableIndex()
                                            : variables.length !== activeVariableIndex + 1
                                            ? incrementActiveVariableIndex()
                                            : null
                                    }
                                >
                                    Continue
                                </LemonButton>
                            ) : null}
                        </>
                    ) : (
                        <div className="flex gap-x-2">
                            <LemonButton
                                type="primary"
                                status="alt"
                                onClick={() => {
                                    setShowCustomEventField(false)
                                    setVariable(variable.name, { events: [FALLBACK_EVENT] })
                                }}
                            >
                                Select from site
                            </LemonButton>
                            <LemonButton type="secondary" onClick={() => setShowCustomEventField(true)}>
                                Use custom event
                            </LemonButton>
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}

export function DashboardTemplateVariables({ hasSelectedSite }: { hasSelectedSite: boolean }): JSX.Element {
    const { activeDashboardTemplate } = useValues(newDashboardLogic)
    const theDashboardTemplateVariablesLogic = dashboardTemplateVariablesLogic({
        variables: activeDashboardTemplate?.variables || [],
    })
    const { variables, activeVariableIndex } = useValues(theDashboardTemplateVariablesLogic)
    const { setVariables, setActiveVariableIndex } = useActions(theDashboardTemplateVariablesLogic)

    // TODO: onboarding-dashboard-templates: this is a hack, I'm not sure why it's not set properly initially.
    useEffect(() => {
        setVariables(activeDashboardTemplate?.variables || [])
    }, [activeDashboardTemplate])

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
                    content: <VariableSelector variable={v} {...v} hasSelectedSite={hasSelectedSite} />,
                    className: 'p-4 bg-white',
                    onHeaderClick: () => {
                        setActiveVariableIndex(i)
                    },
                }))}
                embedded
                size="small"
            />
        </div>
    )
}
