import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheckCircle, IconEye, IconGlobe, IconPeople, IconRocket, IconShield, IconTestTube } from '@posthog/icons'
import { LemonButton, LemonCollapse } from '@posthog/lemon-ui'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { FeatureFlagType, PropertyFilterType, PropertyOperator } from '~/types'

import { userLogic } from '../userLogic'
import { featureFlagLogic } from './featureFlagLogic'

interface TemplateValues {
    key?: string
    name?: string
    active?: boolean
    is_remote_configuration?: boolean
    filters?: FeatureFlagType['filters']
}

interface FlagTemplate {
    id: string
    name: string
    description: string
    icon: React.ReactNode
    getValues: (currentFlag: FeatureFlagType) => TemplateValues
}

interface FeatureFlagTemplatesProps {
    onTemplateApplied?: (sectionsToOpen: string[]) => void
}

export function FeatureFlagTemplates({ onTemplateApplied }: FeatureFlagTemplatesProps): JSX.Element | null {
    const { featureFlag, featureFlagLoading } = useValues(featureFlagLogic)
    const { setFeatureFlag } = useActions(featureFlagLogic)
    const { user } = useValues(userLogic)
    const [isExpanded, setIsExpanded] = useState(true)

    const applyTemplate = (template: FlagTemplate): void => {
        if (!featureFlag) {
            return
        }
        const templateValues = template.getValues(featureFlag)

        setFeatureFlag({
            ...featureFlag,
            ...templateValues,
            filters: {
                ...featureFlag.filters,
                ...templateValues.filters,
            },
        } as FeatureFlagType)

        lemonToast.success(`${template.name} template applied`)
        onTemplateApplied?.(['basics', 'targeting'])
    }

    if (!featureFlag) {
        return null
    }

    // Don't allow template application while the flag is still loading
    // to prevent race conditions where the loader overwrites template values
    const isLoading = featureFlagLoading

    const emailDomain = user?.email?.split('@')[1] || 'example.com'

    const templates: FlagTemplate[] = [
        {
            id: 'percentage-rollout',
            name: 'Gradual Rollout',
            description: 'Gradually roll out to a percentage of users',
            icon: <IconRocket className="text-2xl" />,
            getValues: (flag) => ({
                key: 'gradual-rollout',
                name: 'Gradual rollout to 20% of users',
                is_remote_configuration: false,
                filters: {
                    ...flag.filters,
                    multivariate: null,
                    groups: [{ properties: [], rollout_percentage: 20, variant: null }],
                },
            }),
        },
        {
            id: 'internal-only',
            name: 'Internal Only',
            description: 'Only your team can see this',
            icon: <IconShield className="text-2xl" />,
            getValues: (flag) => ({
                key: 'internal-only',
                name: `Only users with @${emailDomain} emails`,
                is_remote_configuration: false,
                filters: {
                    ...flag.filters,
                    multivariate: null,
                    groups: [
                        {
                            properties: [
                                {
                                    key: 'email',
                                    type: PropertyFilterType.Person,
                                    value: `@${emailDomain}`,
                                    operator: PropertyOperator.IContains,
                                },
                            ],
                            rollout_percentage: 100,
                            variant: null,
                        },
                    ],
                },
            }),
        },
        {
            id: 'beta-users',
            name: 'Beta Users',
            description: 'Target users with a beta property',
            icon: <IconPeople className="text-2xl" />,
            getValues: (flag) => ({
                key: 'beta-feature',
                name: 'Only users with beta property set to true',
                is_remote_configuration: false,
                filters: {
                    ...flag.filters,
                    multivariate: null,
                    groups: [
                        {
                            properties: [
                                {
                                    key: 'beta',
                                    type: PropertyFilterType.Person,
                                    value: ['true'],
                                    operator: PropertyOperator.Exact,
                                },
                            ],
                            rollout_percentage: 100,
                            variant: null,
                        },
                    ],
                },
            }),
        },
        {
            id: 'kill-switch',
            name: 'Kill Switch',
            description: 'Quick on/off for incidents',
            icon: <IconCheckCircle className="text-2xl" />,
            getValues: (flag) => ({
                key: 'kill-switch',
                name: 'Emergency kill switch for…',
                active: true,
                is_remote_configuration: false,
                filters: {
                    ...flag.filters,
                    multivariate: null,
                    groups: [{ properties: [], rollout_percentage: 100, variant: null }],
                },
            }),
        },
        {
            id: 'ab-test',
            name: 'A/B Test',
            description: '50/50 split for experiments',
            icon: <IconTestTube className="text-2xl" />,
            getValues: (flag) => ({
                key: 'ab-test',
                name: '50/50 split between control and test variants',
                is_remote_configuration: false,
                filters: {
                    ...flag.filters,
                    multivariate: {
                        variants: [
                            { key: 'control', rollout_percentage: 50 },
                            { key: 'test', rollout_percentage: 50 },
                        ],
                    },
                    groups: [{ properties: [], rollout_percentage: 100, variant: null }],
                },
            }),
        },
        {
            id: 'canary',
            name: 'Canary',
            description: '1% rollout for safe testing',
            icon: <IconEye className="text-2xl" />,
            getValues: (flag) => ({
                key: 'canary-release',
                name: 'Canary release to 1% of users',
                is_remote_configuration: false,
                filters: {
                    ...flag.filters,
                    multivariate: null,
                    groups: [{ properties: [], rollout_percentage: 1, variant: null }],
                },
            }),
        },
        {
            id: 'geography',
            name: 'By Country',
            description: 'Target users in specific countries',
            icon: <IconGlobe className="text-2xl" />,
            getValues: (flag) => ({
                key: 'country-rollout',
                name: 'Only users in the United States',
                is_remote_configuration: false,
                filters: {
                    ...flag.filters,
                    multivariate: null,
                    groups: [
                        {
                            properties: [
                                {
                                    key: '$geoip_country_code',
                                    type: PropertyFilterType.Person,
                                    value: ['US'],
                                    operator: PropertyOperator.Exact,
                                },
                            ],
                            rollout_percentage: 100,
                            variant: null,
                        },
                    ],
                },
            }),
        },
    ]

    return (
        <>
            <div className="mb-4">
                <LemonCollapse
                    activeKey={isExpanded ? 'templates' : null}
                    onChange={(key) => setIsExpanded(key === 'templates')}
                    panels={[
                        {
                            key: 'templates',
                            header: 'Start with a template',
                            content: (
                                <div className="flex gap-3 overflow-x-auto pt-2">
                                    {templates.map((template) => (
                                        <LemonButton
                                            key={template.id}
                                            type="secondary"
                                            onClick={() => applyTemplate(template)}
                                            disabledReason={isLoading ? 'Loading flag data…' : undefined}
                                            className="flex-shrink-0 w-36 !h-auto !items-start"
                                        >
                                            <div className="flex flex-col text-left py-1">
                                                <div className="text-muted mb-2">{template.icon}</div>
                                                <div className="font-semibold text-sm mb-1">{template.name}</div>
                                                <div className="text-xs text-muted whitespace-normal">
                                                    {template.description}
                                                </div>
                                            </div>
                                        </LemonButton>
                                    ))}
                                </div>
                            ),
                        },
                    ]}
                    embedded
                />
            </div>
            {isExpanded && <h3 className="text-sm font-semibold text-muted mb-2">Or customize your flag</h3>}
        </>
    )
}
