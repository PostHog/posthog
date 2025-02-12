import { LemonCollapse, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'
import { HogFunctionConfiguration } from 'scenes/pipeline/hogfunctions/HogFunctionConfiguration'
import { hogFunctionListLogic } from 'scenes/pipeline/hogfunctions/list/hogFunctionListLogic'

export function ErrorTrackingAlerting(): JSX.Element {
    const [activeKey, setActiveKey] = useState<'issue-created' | undefined>(undefined)
    const logic = hogFunctionListLogic({
        type: 'internal_destination',
        forceFilters: { filters: { type: ['error-tracking-issue-created'] } },
    })
    const { hogFunctions } = useValues(logic)
    const { loadHogFunctions } = useActions(logic)

    const issueCreatedFunction = hogFunctions.find((f) => f.template?.id === 'template-error-tracking-alert')

    useEffect(() => {
        loadHogFunctions()
    }, [])

    return (
        <LemonCollapse
            activeKey={activeKey}
            onChange={(k) => setActiveKey(k || undefined)}
            panels={[
                {
                    key: 'issue-created',
                    header: (
                        <div className="flex flex-1 items-center justify-between">
                            <div className="space-y-1">
                                <div>Issue created</div>
                                <div className="text-muted text-xs">Notify me when a new issue occurs</div>
                            </div>
                            <LemonSwitch
                                checked={false}
                                onChange={() => {
                                    setActiveKey('issue-created')
                                }}
                            />
                        </div>
                    ),
                    className: 'p-0 pb-2',
                    content:
                        activeKey === 'issue-created' || issueCreatedFunction ? (
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
                },
            ]}
        />
    )
}
