import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconPeople, IconRocket, IconShield } from '@posthog/icons'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { FeatureFlagType, PropertyFilterType, PropertyOperator } from '~/types'

import { userLogic } from '../userLogic'
import { featureFlagLogic } from './featureFlagLogic'

interface TemplateValues {
    key?: string
    name?: string
    active?: boolean
    filters?: FeatureFlagType['filters']
}

interface FlagTemplate {
    id: string
    name: string
    description: string
    icon: React.ReactNode
    getValues: () => TemplateValues
}

interface FeatureFlagTemplatesProps {
    onTemplateApplied?: (sectionsToOpen: string[]) => void
}

export function FeatureFlagTemplates({ onTemplateApplied }: FeatureFlagTemplatesProps): JSX.Element {
    const { featureFlag, featureFlagLoading, userEditedFields } = useValues(featureFlagLogic)
    const { setFeatureFlag } = useActions(featureFlagLogic)
    const { user } = useValues(userLogic)

    const applyTemplate = (template: FlagTemplate): void => {
        const templateValues = template.getValues()
        const preservedFields: string[] = []
        const updates: Partial<FeatureFlagType> = { ...featureFlag }

        // Only apply key if user hasn't edited it
        if (templateValues.key !== undefined) {
            if (userEditedFields.has('key')) {
                preservedFields.push('flag key')
            } else {
                updates.key = featureFlag.key || templateValues.key
            }
        }

        // Only apply name/description if user hasn't edited it
        if (templateValues.name !== undefined) {
            if (userEditedFields.has('name')) {
                preservedFields.push('description')
            } else {
                updates.name = featureFlag.name || templateValues.name
            }
        }

        // Only apply active state if user hasn't edited it
        if (templateValues.active !== undefined) {
            if (userEditedFields.has('active')) {
                preservedFields.push('enabled state')
            } else {
                updates.active = templateValues.active
            }
        }

        // Only apply filters if user hasn't edited release conditions
        if (templateValues.filters !== undefined) {
            if (userEditedFields.has('filters')) {
                preservedFields.push('release conditions')
            } else {
                updates.filters = {
                    ...featureFlag.filters,
                    ...templateValues.filters,
                }
            }
        }

        setFeatureFlag(updates as FeatureFlagType)

        if (preservedFields.length > 0) {
            lemonToast.info(
                `Template applied: ${template.name}. Your ${preservedFields.join(', ')} ${preservedFields.length === 1 ? 'was' : 'were'} preserved.`
            )
        } else {
            lemonToast.success(`Template applied: ${template.name}`)
        }
        onTemplateApplied?.(['basics', 'targeting'])
    }

    // Safety check - if featureFlag is not loaded yet, show nothing
    if (!featureFlag) {
        return <div>Loading...</div>
    }

    // Don't allow template application while the flag is still loading
    // to prevent race conditions where the loader overwrites template values
    const isLoading = featureFlagLoading

    const emailDomain = user?.email?.split('@')[1] || 'example.com'

    const templates: FlagTemplate[] = [
        {
            id: 'percentage-rollout',
            name: '% Rollout',
            description: 'Gradually roll out to a percentage of users',
            icon: <IconRocket className="text-2xl" />,
            getValues: () => ({
                key: 'gradual-rollout',
                filters: {
                    ...featureFlag.filters,
                    groups: [
                        {
                            properties: [],
                            rollout_percentage: 20,
                            variant: null,
                        },
                    ],
                },
            }),
        },
        {
            id: 'internal-only',
            name: 'Internal Only',
            description: 'Only your team can see this',
            icon: <IconShield className="text-2xl" />,
            getValues: () => ({
                key: 'internal-only',
                filters: {
                    ...featureFlag.filters,
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
            getValues: () => ({
                key: 'beta-feature',
                filters: {
                    ...featureFlag.filters,
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
            getValues: () => ({
                key: 'kill-switch',
                name: 'Emergency kill switch for…',
                active: true,
                filters: {
                    ...featureFlag.filters,
                    groups: [
                        {
                            properties: [],
                            rollout_percentage: 100,
                            variant: null,
                        },
                    ],
                },
            }),
        },
    ]

    return (
        <div className="mb-4">
            <div className="flex items-center justify-between mb-2">
                <h3 className="mb-0 text-sm font-semibold">Start with a template</h3>
            </div>
            <div className="flex gap-3 overflow-x-auto">
                {templates.map((template) => (
                    <button
                        type="button"
                        key={template.id}
                        onClick={() => applyTemplate(template)}
                        disabled={isLoading}
                        className={`flex-shrink-0 border rounded-lg p-4 w-36 transition-all text-left ${
                            isLoading
                                ? 'opacity-50 cursor-not-allowed'
                                : 'hover:border-primary-light hover:bg-primary-highlight cursor-pointer'
                        }`}
                    >
                        <div className="text-muted mb-2">{template.icon}</div>
                        <div className="font-semibold text-sm mb-1">{template.name}</div>
                        <div className="text-xs text-muted">{template.description}</div>
                    </button>
                ))}
            </div>
        </div>
    )
}
