import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconFlask, IconPeople, IconTestTube, IconToggle } from '@posthog/icons'
import { LemonButton, LemonCollapse } from '@posthog/lemon-ui'

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

export type ModifiedField = 'key' | 'flagType' | 'rollout' | 'conditions'

interface FlagTemplate {
    id: string
    name: string
    description: string
    icon: React.ReactNode
    modifiedFields: ModifiedField[]
    getValues: (currentFlag: FeatureFlagType) => TemplateValues
}

interface FeatureFlagTemplatesProps {
    onTemplateApplied?: (modifiedFields: ModifiedField[]) => void
}

export function FeatureFlagTemplates({ onTemplateApplied }: FeatureFlagTemplatesProps): JSX.Element | null {
    const { featureFlag, featureFlagLoading, templateExpanded, urlTemplateApplied } = useValues(featureFlagLogic)
    const { setFeatureFlag, setTemplateExpanded, applyUrlTemplate, setHighlightedFields } = useActions(featureFlagLogic)
    const { user } = useValues(userLogic)
    const { searchParams } = useValues(router)

    const emailDomain = user?.email?.split('@')[1] || 'example.com'

    const templates: FlagTemplate[] = [
        {
            id: 'simple',
            name: 'Simple flag',
            description: 'On/off for all users',
            icon: <IconToggle className="text-2xl" />,
            modifiedFields: ['key', 'rollout'],
            getValues: (flag) => ({
                key: 'my-feature',
                is_remote_configuration: false,
                filters: {
                    ...flag.filters,
                    multivariate: null,
                    groups: [{ properties: [], rollout_percentage: 100, variant: null }],
                },
            }),
        },
        {
            id: 'targeted',
            name: 'Targeted release',
            description: 'Release to specific users',
            icon: <IconPeople className="text-2xl" />,
            modifiedFields: ['key', 'conditions', 'rollout'],
            getValues: (flag) => ({
                key: 'targeted-release',
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
            id: 'multivariate',
            name: 'Multivariate',
            description: 'Multiple variants',
            icon: <IconTestTube className="text-2xl" />,
            modifiedFields: ['key', 'flagType', 'rollout'],
            getValues: (flag) => ({
                key: 'multivariate-flag',
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
            id: 'targeted-multivariate',
            name: 'Targeted multivariate',
            description: 'Variants for specific users',
            icon: <IconFlask className="text-2xl" />,
            modifiedFields: ['key', 'flagType', 'conditions', 'rollout'],
            getValues: (flag) => ({
                key: 'targeted-multivariate',
                is_remote_configuration: false,
                filters: {
                    ...flag.filters,
                    multivariate: {
                        variants: [
                            { key: 'control', rollout_percentage: 50 },
                            { key: 'test', rollout_percentage: 50 },
                        ],
                    },
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
    ]

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

        setTemplateExpanded(false)
        setHighlightedFields(template.modifiedFields)
        onTemplateApplied?.(template.modifiedFields)
    }

    // Auto-apply template from URL param on first load
    useEffect(() => {
        const templateId = searchParams.template as string | undefined
        if (templateId && featureFlag && !featureFlagLoading && !urlTemplateApplied) {
            const template = templates.find((t) => t.id === templateId)
            if (template) {
                applyTemplate(template)
                applyUrlTemplate(templateId)
            }
        }
    }, [
        searchParams.template,
        featureFlag,
        featureFlagLoading,
        urlTemplateApplied,
        applyTemplate,
        applyUrlTemplate,
        templates,
    ])

    if (!featureFlag) {
        return null
    }

    // Don't allow template application while the flag is still loading
    // to prevent race conditions where the loader overwrites template values
    const isLoading = featureFlagLoading

    return (
        <>
            <div className="mb-4">
                <LemonCollapse
                    // Use a non-matching key instead of null/undefined to force closed state,
                    // because LemonCollapse uses `activeKey ?? localActiveKey` which falls back
                    // to internal state when activeKey is nullish
                    activeKey={templateExpanded ? 'templates' : '__closed__'}
                    onChange={(key) => setTemplateExpanded(key === 'templates')}
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
            {templateExpanded && <h3 className="text-sm font-semibold text-muted mb-2">Or customize your flag</h3>}
        </>
    )
}
