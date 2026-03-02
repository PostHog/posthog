import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonInputSelect } from '@posthog/lemon-ui'

import { LemonRadio } from 'lib/lemon-ui/LemonRadio'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { PropertyDefinitionType, SurveyDisplayConditions, SurveyMatchType } from '~/types'

import { surveyLogic } from '../../surveyLogic'

export function WhereStep(): JSX.Element {
    const { survey } = useValues(surveyLogic)
    const { setSurveyValue } = useActions(surveyLogic)

    const { options } = useValues(propertyDefinitionsModel)
    const { loadPropertyValues } = useActions(propertyDefinitionsModel)
    const urlOptions = options['$current_url']

    const conditions: Partial<SurveyDisplayConditions> = survey.conditions || {}
    const targetingMode = conditions.urlMatchType ? 'specific' : 'all'
    const urlPattern = conditions.url || ''

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

    const setUrlPattern = (pattern: string): void => {
        setSurveyValue('conditions', { ...conditions, url: pattern, urlMatchType: SurveyMatchType.Contains })
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
                    <div className="mt-4 ml-6">
                        <LemonInputSelect
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
                            placeholder="Select a page or type a path like /pricing"
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
                        <p className="text-xs text-muted mt-2">
                            Select from your most visited pages or type a custom pattern
                        </p>
                    </div>
                )}
            </div>
        </div>
    )
}
