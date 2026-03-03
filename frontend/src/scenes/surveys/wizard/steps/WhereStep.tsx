import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonInputSelect, LemonSelect } from '@posthog/lemon-ui'

import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { FeatureFlagReleaseConditions } from 'scenes/feature-flags/FeatureFlagReleaseConditions'
import { DEFAULT_TARGETING_FLAG_FILTERS } from 'scenes/surveys/constants'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { PropertyDefinitionType, SurveyDisplayConditions, SurveyMatchType } from '~/types'

import { SurveyMatchTypeLabels } from '../../constants'
import { surveyLogic } from '../../surveyLogic'

export function WhereStep(): JSX.Element {
    const { survey, targetingFlagFilters } = useValues(surveyLogic)
    const { setSurveyValue } = useActions(surveyLogic)

    const { options } = useValues(propertyDefinitionsModel)
    const { loadPropertyValues } = useActions(propertyDefinitionsModel)
    const urlOptions = options['$current_url']

    const conditions: Partial<SurveyDisplayConditions> = survey.conditions || {}
    const targetingMode = conditions.urlMatchType ? 'specific' : 'all'
    const urlPattern = conditions.url || ''
    const userTargetingMode = targetingFlagFilters ? 'specific' : 'all'

    useEffect(() => {
        if (targetingMode === 'specific' && urlOptions?.status !== 'loading' && urlOptions?.status !== 'loaded') {
            loadPropertyValues({
                endpoint: undefined,
                type: PropertyDefinitionType.Event,
                propertyKey: '$current_url',
                newInput: '',
                eventNames: [],
                properties: [],
            })
        }
    }, [targetingMode, urlOptions?.status, loadPropertyValues])

    const setTargetingMode = (mode: 'all' | 'specific'): void => {
        if (mode === 'all') {
            setSurveyValue('conditions', { ...conditions, url: '', urlMatchType: undefined })
        } else {
            setSurveyValue('conditions', { ...conditions, urlMatchType: SurveyMatchType.Contains })
        }
    }

    const urlMatchType = conditions.urlMatchType || SurveyMatchType.Contains

    const setUrlPattern = (pattern: string): void => {
        setSurveyValue('conditions', { ...conditions, url: pattern, urlMatchType })
    }

    const setUrlMatchType = (matchType: SurveyMatchType): void => {
        setSurveyValue('conditions', { ...conditions, urlMatchType: matchType })
    }

    const setUserTargetingMode = (mode: 'all' | 'specific'): void => {
        if (mode === 'all') {
            setSurveyValue('targeting_flag_filters', null)
            setSurveyValue('targeting_flag', null)
            setSurveyValue('remove_targeting_flag', true)
        } else {
            setSurveyValue('targeting_flag_filters', DEFAULT_TARGETING_FLAG_FILTERS)
            setSurveyValue('remove_targeting_flag', false)
        }
    }

    return (
        <div className="space-y-10">
            {/* Page targeting */}
            <div>
                <h2 className="text-xl font-semibold mb-2">Where should this appear?</h2>
                <p className="text-secondary mb-6">Choose which pages will show this survey</p>

                <LemonRadio
                    value={targetingMode}
                    onChange={setTargetingMode}
                    options={[
                        {
                            value: 'all',
                            label: 'All pages',
                            description: 'Survey can appear anywhere on your site',
                        },
                        {
                            value: 'specific',
                            label: 'Specific pages',
                            description: 'Only show on pages matching a URL pattern',
                        },
                    ]}
                />

                {targetingMode === 'specific' && (
                    <div className="mt-4 ml-6 space-y-2">
                        <div className="flex items-center gap-2">
                            <span className="text-sm whitespace-nowrap">URL</span>
                            <LemonSelect
                                value={urlMatchType}
                                onChange={setUrlMatchType}
                                options={Object.entries(SurveyMatchTypeLabels).map(([key, label]) => ({
                                    label,
                                    value: key as SurveyMatchType,
                                }))}
                                size="small"
                            />
                            <LemonInputSelect
                                className="flex-1"
                                mode="single"
                                value={urlPattern ? [urlPattern] : []}
                                onChange={(val) => setUrlPattern(val[0] || '')}
                                onInputChange={(newInput) => {
                                    loadPropertyValues({
                                        type: PropertyDefinitionType.Event,
                                        endpoint: undefined,
                                        propertyKey: '$current_url',
                                        newInput: newInput.trim(),
                                        eventNames: [],
                                        properties: [],
                                    })
                                }}
                                placeholder="e.g. /pricing"
                                allowCustomValues
                                loading={urlOptions?.status === 'loading'}
                                options={(() => {
                                    const seen = new Set<string>()
                                    return (urlOptions?.values || [])
                                        .map(({ name }) => {
                                            const url = String(name)
                                            let path = url
                                            try {
                                                const parsed = new URL(url)
                                                path = parsed.pathname
                                            } catch {
                                                // Keep as-is if not a valid URL
                                            }
                                            return path
                                        })
                                        .filter((path) => {
                                            if (seen.has(path)) {
                                                return false
                                            }
                                            seen.add(path)
                                            return true
                                        })
                                        .map((path) => ({ key: path, label: path }))
                                })()}
                            />
                        </div>
                    </div>
                )}
            </div>

            {/* User targeting */}
            <div>
                <h2 className="text-xl font-semibold mb-2">Who should see this?</h2>
                <p className="text-secondary mb-6">Target specific users based on their properties</p>

                <LemonRadio
                    value={userTargetingMode}
                    onChange={setUserTargetingMode}
                    options={[
                        {
                            value: 'all',
                            label: 'All users',
                            description: 'Any user can see this survey',
                        },
                        {
                            value: 'specific',
                            label: 'Users matching conditions',
                            description: 'Only show to users that match property filters',
                        },
                    ]}
                />

                {userTargetingMode === 'specific' && (
                    <div className="mt-4 ml-6">
                        <BindLogic
                            logic={featureFlagLogic}
                            props={{ id: survey.targeting_flag?.id ? String(survey.targeting_flag.id) : 'new' }}
                        >
                            <FeatureFlagReleaseConditions
                                id={survey.targeting_flag?.id ? String(survey.targeting_flag.id) : 'new'}
                                excludeTitle
                                hideMatchOptions
                                filters={targetingFlagFilters || DEFAULT_TARGETING_FLAG_FILTERS}
                                onChange={(filters) => {
                                    setSurveyValue('targeting_flag_filters', filters)
                                }}
                                showTrashIconWithOneCondition
                                removedLastConditionCallback={() => setUserTargetingMode('all')}
                            />
                        </BindLogic>
                    </div>
                )}
            </div>
        </div>
    )
}
