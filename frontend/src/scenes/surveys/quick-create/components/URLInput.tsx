import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonInputSelect, LemonLabel } from '@posthog/lemon-ui'

import { quickSurveyFormLogic } from 'scenes/surveys/quick-create/quickSurveyFormLogic'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { PropertyDefinitionType } from '~/types'

export function URLInput(): JSX.Element {
    const { surveyForm } = useValues(quickSurveyFormLogic)
    const { updateConditions } = useActions(quickSurveyFormLogic)

    const { options } = useValues(propertyDefinitionsModel)
    const { loadPropertyValues } = useActions(propertyDefinitionsModel)

    const targetUrl = surveyForm.conditions?.url || ''
    const urlOptions = options['$current_url']

    useEffect(() => {
        if (urlOptions?.status !== 'loading' && urlOptions?.status !== 'loaded') {
            loadPropertyValues({
                endpoint: undefined,
                type: PropertyDefinitionType.Event,
                propertyKey: '$current_url',
                newInput: '',
                eventNames: [],
                properties: [],
            })
        }
    }, [urlOptions?.status, loadPropertyValues])

    return (
        <div>
            <LemonLabel className="mb-2">Target specific URL (optional)</LemonLabel>
            <LemonInputSelect
                mode="single"
                value={targetUrl ? [targetUrl] : []}
                onChange={(val) => updateConditions({ url: val[0] || undefined })}
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
                placeholder="All URLs"
                allowCustomValues
                loading={urlOptions?.status === 'loading'}
                options={(urlOptions?.values || []).map(({ name }) => ({
                    key: String(name),
                    label: String(name),
                    value: String(name),
                }))}
                data-attr="quick-survey-url-input"
            />
        </div>
    )
}
