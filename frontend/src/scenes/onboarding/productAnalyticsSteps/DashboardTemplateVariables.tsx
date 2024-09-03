import { IconCheckCircle, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonLabel } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { dashboardTemplateVariablesLogic } from 'scenes/dashboard/dashboardTemplateVariablesLogic'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'

import { DashboardTemplateVariableType } from '~/types'

function VariableSelector({ variable }: { variable: DashboardTemplateVariableType }): JSX.Element {
    const { activeDashboardTemplate } = useValues(newDashboardLogic)
    const theDashboardTemplateVariablesLogic = dashboardTemplateVariablesLogic({
        variables: activeDashboardTemplate?.variables || [],
    })
    const { setVariable, resetVariable, incrementActiveVariableIndex } = useActions(theDashboardTemplateVariablesLogic)

    const FALLBACK_EVENT = {
        id: '$other_event',
        math: 'dau',
        type: 'events',
    }

    return (
        <div className="pl-7">
            <div className="mb-2">
                <p>Select the element that indicates:</p>
                <LemonLabel showOptional={!variable.required} info={<>{variable.description}</>}>
                    {variable.name}
                </LemonLabel>
            </div>
            {variable.touched && (
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
            <div className="flex">
                {variable.touched ? (
                    <LemonButton type="primary" status="alt" onClick={incrementActiveVariableIndex}>
                        Continue
                    </LemonButton>
                ) : (
                    <LemonButton
                        type="primary"
                        status="alt"
                        onClick={() => setVariable(variable.name, { events: [FALLBACK_EVENT] })}
                    >
                        Select from site
                    </LemonButton>
                )}
            </div>
        </div>
    )
}

export function DashboardTemplateVariables(): JSX.Element {
    const { activeDashboardTemplate } = useValues(newDashboardLogic)
    const theDashboardTemplateVariablesLogic = dashboardTemplateVariablesLogic({
        variables: activeDashboardTemplate?.variables || [],
    })
    const { variables, activeVariableIndex } = useValues(theDashboardTemplateVariablesLogic)
    const { setVariables } = useActions(theDashboardTemplateVariablesLogic)

    // TODO: onboarding-dashboard-templates: this is a hack, I'm not sure why it's not set properly initially.
    useEffect(() => {
        setVariables(activeDashboardTemplate?.variables || [])
    }, [activeDashboardTemplate])

    return (
        <div className="mb-4 DashboardTemplateVariables max-w-192">
            <LemonCollapse
                activeKey={variables[activeVariableIndex]?.id}
                panels={variables.map((v) => ({
                    key: v.id,
                    header: (
                        <div>
                            {v.name}
                            {v.touched && <IconCheckCircle className="text-success ml-2 text-base" />}
                        </div>
                    ),
                    content: <VariableSelector variable={v} {...v} />,
                    className: 'p-4 bg-white',
                }))}
                embedded
                size="small"
            />
        </div>
    )
}
