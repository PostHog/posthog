import { useActions, } from 'kea'
import { useEffect, useState } from 'react'

import { IconFlask, IconLive, IconWarning, IconPlay, IconComment } from '@posthog/icons'
import { LemonButton, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import api from 'lib/api'

import { DashboardWidgetType } from '~/types'

import { dashboardLogic } from './dashboardLogic'

const WIDGET_TYPE_OPTIONS = [
    {
        value: DashboardWidgetType.Experiment,
        label: 'Experiment',
        icon: <IconFlask />,
        description: 'View details of an experiment',
        needsId: true,
        idLabel: 'Experiment',
    },
    {
        value: DashboardWidgetType.Logs,
        label: 'Logs',
        icon: <IconLive />,
        description: 'Live log viewer with filters',
        needsId: false,
    },
    {
        value: DashboardWidgetType.ErrorTracking,
        label: 'Error tracking',
        icon: <IconWarning />,
        description: 'Filtered view of error issues',
        needsId: false,
    },
    {
        value: DashboardWidgetType.SessionReplays,
        label: 'Session replays',
        icon: <IconPlay />,
        description: 'Filtered list of session recordings',
        needsId: false,
    },
    {
        value: DashboardWidgetType.SurveyResponses,
        label: 'Survey responses',
        icon: <IconComment />,
        description: 'Latest responses from a survey',
        needsId: true,
        idLabel: 'Survey',
    },
] as const

interface AddWidgetModalProps {
    isOpen: boolean
    onClose: () => void
    initialWidgetType?: DashboardWidgetType
}

interface SelectOption {
    value: string | number
    label: string
}

export function AddWidgetModal({ isOpen, onClose, initialWidgetType }: AddWidgetModalProps): JSX.Element {
    const { addWidget } = useActions(dashboardLogic)

    const [selectedType, setSelectedType] = useState<DashboardWidgetType | null>(initialWidgetType ?? null)
    const [selectedId, setSelectedId] = useState<number | null>(null)
    const [options, setOptions] = useState<SelectOption[]>([])
    const [loadingOptions, setLoadingOptions] = useState(false)

    const widgetOption = WIDGET_TYPE_OPTIONS.find((o) => o.value === selectedType)
    const needsId = widgetOption?.needsId ?? false

    useEffect(() => {
        if (initialWidgetType) {
            setSelectedType(initialWidgetType)
        }
    }, [initialWidgetType])

    useEffect(() => {
        if (!selectedType || !needsId) {
            setOptions([])
            return
        }

        setLoadingOptions(true)
        setSelectedId(null)

        let endpoint = ''
        if (selectedType === DashboardWidgetType.Experiment) {
            endpoint = 'api/projects/@current/experiments'
        } else if (selectedType === DashboardWidgetType.SurveyResponses) {
            endpoint = 'api/projects/@current/surveys'
        }

        if (endpoint) {
            api.get(endpoint)
                .then((data: any) => {
                    const results = data.results || data || []
                    setOptions(
                        results.map((item: any) => ({
                            value: item.id,
                            label: item.name || `#${item.id}`,
                        }))
                    )
                    setLoadingOptions(false)
                })
                .catch(() => {
                    setLoadingOptions(false)
                })
        }
    }, [selectedType, needsId])

    const handleAdd = (): void => {
        if (!selectedType) {
            return
        }

        let config: Record<string, any> = {}
        if (selectedType === DashboardWidgetType.Experiment) {
            config = { experiment_id: selectedId }
        } else if (selectedType === DashboardWidgetType.SurveyResponses) {
            config = { survey_id: selectedId }
        } else if (selectedType === DashboardWidgetType.Logs) {
            config = { filters: {} }
        } else if (selectedType === DashboardWidgetType.ErrorTracking) {
            config = { status: 'active' }
        } else if (selectedType === DashboardWidgetType.SessionReplays) {
            config = {}
        }

        addWidget(selectedType, config)
        onClose()
        resetState()
    }

    const resetState = (): void => {
        setSelectedType(null)
        setSelectedId(null)
        setOptions([])
    }

    const canAdd = selectedType && (!needsId || selectedId)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={() => {
                onClose()
                resetState()
            }}
            title="Add widget"
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={() => {
                            onClose()
                            resetState()
                        }}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={handleAdd} disabledReason={!canAdd ? 'Select a widget type' : undefined}>
                        Add widget
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-4">
                <div>
                    <label className="text-sm font-medium mb-1 block">Widget type</label>
                    <div className="grid grid-cols-1 gap-2">
                        {WIDGET_TYPE_OPTIONS.map((option) => (
                            <button
                                key={option.value}
                                type="button"
                                className={`flex items-center gap-3 p-3 rounded border text-left transition-colors ${
                                    selectedType === option.value
                                        ? 'border-primary bg-primary/5'
                                        : 'border-border hover:border-primary/50'
                                }`}
                                onClick={() => setSelectedType(option.value)}
                            >
                                <span className="text-lg">{option.icon}</span>
                                <div>
                                    <div className="font-medium text-sm">{option.label}</div>
                                    <div className="text-xs text-muted">{option.description}</div>
                                </div>
                            </button>
                        ))}
                    </div>
                </div>

                {needsId && selectedType && (
                    <div>
                        <label className="text-sm font-medium mb-1 block">
                            Select {widgetOption?.idLabel?.toLowerCase()}
                        </label>
                        <LemonSelect
                            options={options}
                            value={selectedId}
                            onChange={(value) => setSelectedId(value)}
                            placeholder={`Select a ${widgetOption?.idLabel?.toLowerCase()}...`}
                            loading={loadingOptions}
                            fullWidth
                        />
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
