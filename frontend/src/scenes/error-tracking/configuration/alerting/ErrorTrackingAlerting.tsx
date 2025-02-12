import { LemonCollapse, LemonCollapsePanel, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'
import { HogFunctionConfiguration } from 'scenes/pipeline/hogfunctions/HogFunctionConfiguration'
import { hogFunctionListLogic } from 'scenes/pipeline/hogfunctions/list/hogFunctionListLogic'

import { HogFunctionType } from '~/types'

enum ErrorTrackingAlertTemplate {
    IssueCreated = 'error-tracking-issue-created',
}

type ErrorTrackingAlert = { type: ErrorTrackingAlertTemplate; title: string; description: string }

const ALERTS: ErrorTrackingAlert[] = [
    {
        type: ErrorTrackingAlertTemplate.IssueCreated,
        title: 'Issue created',
        description: 'Notify me when a new issue occurs',
    },
]

export function ErrorTrackingAlerting(): JSX.Element {
    const logic = hogFunctionListLogic({
        type: 'internal_destination',
        forceFilters: { filters: { type: [ErrorTrackingAlertTemplate.IssueCreated] } },
    })
    const { hogFunctions } = useValues(logic)
    const { loadHogFunctions, toggleEnabled } = useActions(logic)
    const [activeKey, setActiveKey] = useState<ErrorTrackingAlertTemplate | undefined>(undefined)

    useEffect(() => {
        loadHogFunctions()
    }, [])

    return (
        <LemonCollapse
            activeKey={activeKey}
            onChange={(k) => setActiveKey(k || undefined)}
            panels={ALERTS.map(({ type }) =>
                panel({
                    type,
                    hogFn: hogFunctions.find((f) => f.template?.id === `template-slack-${type}`),
                    active: activeKey === type,
                    toggleFunction: toggleEnabled,
                    setActiveKey,
                })
            )}
        />
    )
}

const panel = ({
    type,
    hogFn,
    active,
    toggleFunction,
    setActiveKey,
}: {
    type: ErrorTrackingAlert['type']
    hogFn?: HogFunctionType
    active: boolean
    toggleFunction: (hogFunction: HogFunctionType, enabled: boolean) => void
    setActiveKey: (value: ErrorTrackingAlertTemplate | undefined) => void
}): LemonCollapsePanel<ErrorTrackingAlertTemplate> => {
    return {
        key: type,
        header: (
            <div className="flex flex-1 items-center justify-between">
                <div className="space-y-1">
                    <div>Issue created</div>
                    <div className="text-muted text-xs">Notify me when a new issue occurs</div>
                </div>
                <LemonSwitch
                    checked={hogFn ? hogFn.enabled : active}
                    onChange={(value) =>
                        hogFn ? toggleFunction(hogFn, value) : setActiveKey(value ? type : undefined)
                    }
                />
            </div>
        ),
        className: 'p-0 pb-2',
        content:
            active || hogFn ? (
                <HogFunctionConfiguration
                    id={null}
                    templateId="template-slack-error-tracking-issue-created"
                    displayOptions={{
                        embedded: true,
                        hidePageHeader: true,
                        hideOverview: true,
                        showFilters: false,
                        showExpectedVolume: false,
                        showTesting: false,
                        canEditSource: false,
                        showPersonsCount: false,
                    }}
                />
            ) : null,
    }
}
