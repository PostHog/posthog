import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'

import { AnyPropertyFilter, FeatureFlagFilters } from '~/types'

import { surveyLogic } from '../surveyLogic'
import {
    getSurveyAudienceRuleCount,
    getSurveyAudienceRolloutPercentage,
    getSurveyAudienceSummaryValue,
    getSurveyTargetingFilters,
    isSimpleSurveyAudienceTargeting,
} from '../utils'
import { WizardPanel, WizardSection } from './WizardLayout'

function buildSimpleAudienceFilters(properties: AnyPropertyFilter[], rolloutPercentage: number): FeatureFlagFilters {
    return {
        groups: [
            {
                properties,
                rollout_percentage: rolloutPercentage,
                variant: null,
            },
        ],
        multivariate: null,
        payloads: {},
    }
}

export function SurveyAudienceFilters({ onOpenFullEditor }: { onOpenFullEditor?: () => void }): JSX.Element {
    const { survey } = useValues(surveyLogic)
    const { setSurveyValue, setFlagPropertyErrors } = useActions(surveyLogic)

    const targetingFilters = getSurveyTargetingFilters(survey)
    const isSimpleTargeting = isSimpleSurveyAudienceTargeting(targetingFilters)
    const simpleAudienceFilters = isSimpleTargeting ? targetingFilters?.groups[0]?.properties || [] : []
    const audienceRuleCount = getSurveyAudienceRuleCount(targetingFilters)
    const rolloutPercentage = isSimpleTargeting ? (getSurveyAudienceRolloutPercentage(targetingFilters) ?? 100) : 100
    const hasAdvancedTargeting = !!targetingFilters && !isSimpleTargeting
    const hasAudienceRules = audienceRuleCount > 0
    const hasGuidedAudienceConfig = hasAudienceRules || rolloutPercentage < 100

    const [audienceMode, setAudienceMode] = useState<'all' | 'specific'>(hasGuidedAudienceConfig ? 'specific' : 'all')

    useEffect(() => {
        if (hasAdvancedTargeting) {
            setAudienceMode('specific')
            return
        }

        if (hasGuidedAudienceConfig) {
            setAudienceMode('specific')
            return
        }

        setAudienceMode((current) => (current === 'specific' ? current : 'all'))
    }, [hasAdvancedTargeting, hasGuidedAudienceConfig])

    const clearAudienceFilters = (): void => {
        setSurveyValue('targeting_flag_filters', null)
        setSurveyValue('targeting_flag', null)
        setSurveyValue('remove_targeting_flag', true)
        setFlagPropertyErrors(null)
    }

    const handleAudienceModeChange = (mode: 'all' | 'specific'): void => {
        setAudienceMode(mode)

        if (mode === 'all') {
            clearAudienceFilters()
            return
        }

        setSurveyValue('remove_targeting_flag', false)
        setFlagPropertyErrors(null)
    }

    const handleRolloutChange = (value: number): void => {
        const nextValue = Math.max(0, Math.min(100, value))

        setFlagPropertyErrors(null)

        if (simpleAudienceFilters.length === 0 && nextValue === 100) {
            clearAudienceFilters()
            return
        }

        setSurveyValue('targeting_flag_filters', buildSimpleAudienceFilters(simpleAudienceFilters, nextValue))
        setSurveyValue('remove_targeting_flag', false)
    }

    const handleFiltersChange = (filters: AnyPropertyFilter[]): void => {
        setFlagPropertyErrors(null)

        if (filters.length === 0 && rolloutPercentage === 100) {
            clearAudienceFilters()
            return
        }

        setSurveyValue('targeting_flag_filters', buildSimpleAudienceFilters(filters, rolloutPercentage))
        setSurveyValue('remove_targeting_flag', false)
    }

    const headerSummary = getSurveyAudienceSummaryValue(survey) || (audienceMode === 'all' ? 'Everyone' : null)

    return (
        <WizardSection
            title="Who should see this?"
            description="Narrow this survey to people or cohorts, and control how broadly it rolls out."
            className="space-y-2.5"
            badge={
                headerSummary ? (
                    <span className="rounded bg-surface-secondary px-2 py-1 text-xs text-secondary">
                        {headerSummary}
                    </span>
                ) : null
            }
        >
            {hasAdvancedTargeting ? (
                <div className="space-y-2.5">
                    <WizardPanel>
                        <div className="text-sm font-medium text-primary">Advanced audience targeting</div>
                        <div className="mt-1 text-xs text-secondary">
                            This survey already uses targeting rules that are more advanced than the guided editor
                            supports.
                        </div>
                    </WizardPanel>
                    <div className="flex items-center justify-between gap-3">
                        <p className="m-0 text-xs text-muted">Use the full editor to review or change these rules.</p>
                        {onOpenFullEditor && (
                            <LemonButton type="secondary" size="small" onClick={onOpenFullEditor}>
                                Open full editor
                            </LemonButton>
                        )}
                    </div>
                </div>
            ) : (
                <div className="space-y-2.5">
                    <LemonRadio
                        value={audienceMode}
                        onChange={handleAudienceModeChange}
                        options={[
                            {
                                value: 'all',
                                label: 'Everyone',
                                description: 'Show this survey to anyone who matches the display conditions.',
                            },
                            {
                                value: 'specific',
                                label: 'Specific people',
                                description:
                                    'Only show this survey to matching people or cohorts, with an optional rollout.',
                            },
                        ]}
                    />

                    {audienceMode === 'specific' && (
                        <div className="ml-6 space-y-2.5">
                            <WizardPanel>
                                <div className="text-xs font-medium uppercase tracking-wide text-muted-alt">
                                    Rollout
                                </div>
                                <div className="mt-1 text-xs text-secondary">
                                    Show this survey to {rolloutPercentage}% of matching users. Default is 100%.
                                </div>
                                <div className="mt-3 flex items-center gap-3">
                                    <LemonSlider
                                        value={rolloutPercentage}
                                        onChange={handleRolloutChange}
                                        min={0}
                                        max={100}
                                        step={1}
                                        className="flex-1"
                                        ticks={[
                                            { value: 0, label: '0%' },
                                            { value: 25, label: '25%' },
                                            { value: 50, label: '50%' },
                                            { value: 100, label: '100%' },
                                        ]}
                                    />
                                    <LemonInput
                                        type="number"
                                        min={0}
                                        max={100}
                                        step="1"
                                        value={rolloutPercentage}
                                        onChange={(value) => handleRolloutChange(value ?? 100)}
                                        className="w-24"
                                        suffix={<span>%</span>}
                                    />
                                </div>
                            </WizardPanel>

                            <WizardPanel>
                                <div className="text-xs font-medium uppercase tracking-wide text-muted-alt">
                                    Audience rules
                                </div>
                                <div className="mt-1 text-xs text-secondary">
                                    Match people whose properties meet all of these rules. You can also target saved
                                    cohorts.
                                </div>
                                <div className="mt-3">
                                    <PropertyFilters
                                        propertyFilters={simpleAudienceFilters}
                                        onChange={handleFiltersChange}
                                        pageKey="survey-wizard-audience-filters"
                                        taxonomicGroupTypes={[
                                            TaxonomicFilterGroupType.PersonProperties,
                                            TaxonomicFilterGroupType.Cohorts,
                                        ]}
                                        buttonText="Add audience rule"
                                        buttonSize="small"
                                        openOnInsert
                                    />
                                </div>
                            </WizardPanel>

                            <div className="flex items-center justify-between gap-3">
                                <p className="m-0 text-xs text-muted">
                                    Need OR groups or more advanced targeting? Use the full editor.
                                </p>
                                {onOpenFullEditor && (
                                    <LemonButton type="tertiary" size="small" onClick={onOpenFullEditor}>
                                        Open full editor
                                    </LemonButton>
                                )}
                            </div>
                        </div>
                    )}
                </div>
            )}
        </WizardSection>
    )
}
