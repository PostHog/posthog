import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonInputSelect, LemonSegmentedButton } from '@posthog/lemon-ui'

import { FlagSelector } from 'lib/components/FlagSelector'
import { ANY_VARIANT, variantOptions } from 'lib/components/IngestionControls/triggers/FlagTrigger/VariantSelector'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { PropertyDefinitionType, SurveyDisplayConditions, SurveyMatchType } from '~/types'

import { surveyLogic } from '../../surveyLogic'
import { SurveyAudienceFilters } from '../SurveyAudienceFilters'
import { WizardSection, WizardStepLayout } from '../WizardLayout'

const DEVICE_OPTIONS = ['Desktop', 'Mobile', 'Tablet']

export function WhereStep({ onOpenFullEditor }: { onOpenFullEditor?: () => void }): JSX.Element {
    const { survey } = useValues(surveyLogic)
    const { setSurveyValue } = useActions(surveyLogic)
    const { featureFlag } = useValues(featureFlagLogic({ id: survey.linked_flag_id || 'link' }))

    const { options } = useValues(propertyDefinitionsModel)
    const { loadPropertyValues } = useActions(propertyDefinitionsModel)
    const urlOptions = options['$current_url']

    const conditions: Partial<SurveyDisplayConditions> = survey.conditions || {}
    const targetingMode = conditions.urlMatchType ? 'specific' : 'all'
    const urlPattern = conditions.url || ''
    const urlMatchMode =
        conditions.urlMatchType === SurveyMatchType.Exact ? SurveyMatchType.Exact : SurveyMatchType.Contains
    const isPathInputInExactMode = urlMatchMode === SurveyMatchType.Exact && urlPattern.trim().startsWith('/')
    const selectedDevices = conditions.deviceTypes || []
    const resolvedLinkedFlag = survey.linked_flag || (survey.linked_flag_id ? featureFlag : null)
    const urlInputPlaceholder =
        urlMatchMode === SurveyMatchType.Exact
            ? 'Select a page or type the full URL'
            : 'Select a page or type a path like /pricing'
    const urlSuggestions = (() => {
        const seen = new Set<string>()

        return (urlOptions?.values || [])
            .map(({ name }) => {
                const rawValue = String(name)

                if (urlMatchMode === SurveyMatchType.Exact) {
                    try {
                        return new URL(rawValue).toString()
                    } catch {
                        return null
                    }
                }

                try {
                    return new URL(rawValue).pathname || '/'
                } catch {
                    return rawValue
                }
            })
            .filter((value): value is string => !!value)
            .filter((value) => {
                if (seen.has(value)) {
                    return false
                }
                seen.add(value)
                return true
            })
            .map((value) => ({ key: value, label: value }))
    })()

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
        setSurveyValue('conditions', { ...conditions, url: pattern, urlMatchType: urlMatchMode })
    }

    const setUrlMatchMode = (matchType: SurveyMatchType.Exact | SurveyMatchType.Contains): void => {
        setSurveyValue('conditions', {
            ...conditions,
            urlMatchType: matchType,
        })
    }

    const toggleDeviceType = (device: string): void => {
        const nextDeviceTypes = selectedDevices.includes(device)
            ? selectedDevices.filter((current) => current !== device)
            : [...selectedDevices, device]

        setSurveyValue('conditions', {
            ...conditions,
            deviceTypes: nextDeviceTypes.length > 0 ? nextDeviceTypes : undefined,
            deviceTypesMatchType: nextDeviceTypes.length > 0 ? SurveyMatchType.Exact : undefined,
        })
    }

    const clearLinkedFlag = (): void => {
        const { linkedFlagVariant, ...restConditions } = conditions
        setSurveyValue('linked_flag_id', null)
        setSurveyValue('linked_flag', null)
        setSurveyValue('conditions', restConditions)
    }

    return (
        <WizardStepLayout className="space-y-6">
            <WizardSection title="Where should this appear?" description="Choose which pages will show this survey">
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
                            description: 'Only show on pages matching a path or full URL',
                        },
                    ]}
                />

                {targetingMode === 'specific' && (
                    <div className="mt-3 ml-6">
                        <div className="mb-2">
                            <LemonSegmentedButton
                                value={urlMatchMode}
                                onChange={(value) =>
                                    setUrlMatchMode(value as SurveyMatchType.Exact | SurveyMatchType.Contains)
                                }
                                options={[
                                    { value: SurveyMatchType.Contains, label: 'Contains path' },
                                    { value: SurveyMatchType.Exact, label: 'Exact URL' },
                                ]}
                                size="small"
                            />
                        </div>
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
                            placeholder={urlInputPlaceholder}
                            allowCustomValues
                            status={isPathInputInExactMode ? 'danger' : undefined}
                            loading={urlOptions?.status === 'loading'}
                            options={urlSuggestions}
                        />
                        {isPathInputInExactMode ? (
                            <p className="text-xs text-danger mt-1.5">
                                Exact URL requires the full URL, including protocol and host. Use Contains path for
                                entries like /pricing.
                            </p>
                        ) : (
                            <p className="text-xs text-muted mt-1.5">
                                {urlMatchMode === SurveyMatchType.Exact
                                    ? 'Select from your most visited pages or type the full URL, including protocol and host.'
                                    : 'Select from your most visited pages or type a path like /pricing.'}
                            </p>
                        )}
                    </div>
                )}
            </WizardSection>

            <SurveyAudienceFilters onOpenFullEditor={onOpenFullEditor} />

            <WizardSection
                title="Which devices should this appear on?"
                description="Choose whether this survey should show on desktop, mobile, tablet, or any combination."
            >
                <div className="flex flex-wrap gap-2">
                    {DEVICE_OPTIONS.map((device) => {
                        const selected = selectedDevices.includes(device)

                        return (
                            <LemonButton
                                key={device}
                                type={selected ? 'primary' : 'secondary'}
                                size="small"
                                onClick={() => toggleDeviceType(device)}
                            >
                                {device}
                            </LemonButton>
                        )
                    })}
                </div>
                <p className="text-xs text-muted mt-1.5">
                    Leave all unselected to show the survey on every device type.
                </p>
            </WizardSection>

            <WizardSection
                title="Feature flag targeting"
                description="Optionally limit this survey to users who have a specific feature flag enabled."
            >
                <div className="space-y-2.5">
                    <div className="flex items-center gap-2">
                        <FlagSelector
                            value={survey.linked_flag_id || undefined}
                            onChange={(id, _key, flag) => {
                                const { linkedFlagVariant, ...restConditions } = conditions
                                setSurveyValue('linked_flag_id', id)
                                setSurveyValue('linked_flag', flag)
                                setSurveyValue('conditions', restConditions)
                            }}
                            initialButtonLabel="Select feature flag"
                        />
                        {survey.linked_flag_id && (
                            <LemonButton type="tertiary" size="small" icon={<IconTrash />} onClick={clearLinkedFlag}>
                                Clear
                            </LemonButton>
                        )}
                    </div>

                    {resolvedLinkedFlag?.filters.multivariate && (
                        <div className="ml-6 space-y-3">
                            <div>
                                <div className="text-sm font-medium mb-2">Flag variant</div>
                                <LemonSegmentedButton
                                    value={conditions.linkedFlagVariant ?? ANY_VARIANT}
                                    options={variantOptions(resolvedLinkedFlag.filters.multivariate)}
                                    onChange={(variant) => {
                                        setSurveyValue('conditions', {
                                            ...conditions,
                                            linkedFlagVariant: variant === ANY_VARIANT ? null : String(variant),
                                        })
                                    }}
                                />
                            </div>
                            <p className="text-xs text-muted">
                                Choose a specific variant or keep it on any enabled variant.
                            </p>
                        </div>
                    )}
                </div>
            </WizardSection>
        </WizardStepLayout>
    )
}
