import { useValues } from 'kea'
import { groupsModel } from 'models/groupsModel'
import { useRef } from 'react'

import { IconCheckCircle, IconLaptop, IconPeople, IconPerson } from '@posthog/icons'
import { LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Link } from 'lib/lemon-ui/Link'

export type BucketingOption = 'user' | 'device' | 'group'

export interface BucketingIdentifierValue {
    option: BucketingOption
    aggregationGroupTypeIndex?: number | null
}

interface BucketingIdentifierSelectorProps {
    value: BucketingIdentifierValue
    onChange: (value: BucketingIdentifierValue) => void
    disabled?: boolean
}

export function BucketingIdentifierSelector({
    value,
    onChange,
    disabled = false,
}: BucketingIdentifierSelectorProps): JSX.Element | null {
    const { groupTypes, showGroupsOptions } = useValues(groupsModel)
    const optionRefs = useRef<Record<string, HTMLDivElement | null>>({})

    const groupTypeValues = Array.from(groupTypes.values())
    const hasGroups = showGroupsOptions && groupTypeValues.length > 0

    const options: {
        value: BucketingOption
        icon: JSX.Element
        label: string
        description: string
        badge?: { type: 'warning' | 'highlight'; text: string }
        learnMoreUrl?: string
    }[] = [
        {
            value: 'user',
            icon: <IconPerson className="text-base shrink-0" />,
            label: 'User',
            description: 'Stable assignment for logged-in users based on their distinct ID.',
        },
        {
            value: 'device',
            icon: <IconLaptop className="text-base shrink-0" />,
            label: 'Device',
            description: 'Stable assignment per device. Good fit for experiments on anonymous users.',
            badge: { type: 'warning', text: 'BETA' },
            learnMoreUrl: 'https://posthog.com/docs/feature-flags/device-bucketing',
        },
        ...(hasGroups
            ? [
                  {
                      value: 'group' as const,
                      icon: <IconPeople className="text-base shrink-0" />,
                      label: 'Group',
                      description:
                          'Stable assignment for everyone in an organization, company, or other custom group type.',
                  },
              ]
            : []),
    ]

    const selectOption = (optionValue: BucketingOption): void => {
        if (disabled) {
            return
        }
        if (optionValue === 'group') {
            const firstGroupType = groupTypeValues[0]
            onChange({
                option: 'group',
                aggregationGroupTypeIndex: firstGroupType?.group_type_index ?? null,
            })
        } else {
            onChange({
                option: optionValue,
                aggregationGroupTypeIndex: null,
            })
        }
    }

    return (
        <div>
            <LemonLabel className="mb-2" id="experiment-bucketing-label">
                Bucketing identifier
            </LemonLabel>
            <div
                role="radiogroup"
                aria-labelledby="experiment-bucketing-label"
                className="flex flex-wrap gap-2"
                data-attr="experiment-bucketing-identifier"
                onKeyDown={(e) => {
                    if (disabled) {
                        return
                    }
                    if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)) {
                        e.preventDefault()
                        const optionValues = options.map((o) => o.value)
                        const currentIndex = optionValues.indexOf(value.option)
                        let nextIndex = currentIndex

                        if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') {
                            nextIndex = currentIndex > 0 ? currentIndex - 1 : optionValues.length - 1
                        } else if (e.key === 'ArrowDown' || e.key === 'ArrowRight') {
                            nextIndex = currentIndex < optionValues.length - 1 ? currentIndex + 1 : 0
                        }

                        selectOption(optionValues[nextIndex])
                        optionRefs.current[optionValues[nextIndex]]?.focus()
                    }
                }}
            >
                {options.map((option) => {
                    const isSelected = option.value === value.option

                    return (
                        <div
                            key={option.value}
                            ref={(el) => {
                                optionRefs.current[option.value] = el
                            }}
                            role="radio"
                            aria-checked={isSelected}
                            tabIndex={isSelected ? 0 : -1}
                            className={`rounded p-3 cursor-pointer transition-colors flex-1 min-w-0 ${
                                disabled
                                    ? 'opacity-50 cursor-not-allowed'
                                    : isSelected
                                      ? 'bg-accent-highlight-light border-2 border-accent'
                                      : 'border bg-surface-primary border-primary hover:bg-fill-button-tertiary-hover'
                            }`}
                            onClick={() => selectOption(option.value)}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter' || e.key === ' ') {
                                    e.preventDefault()
                                    selectOption(option.value)
                                }
                            }}
                            data-attr={`experiment-bucketing-${option.value}`}
                        >
                            <div className="flex flex-col gap-1">
                                <div className="flex items-center gap-1.5">
                                    {option.icon}
                                    <span className="text-sm font-medium flex-1 truncate" title={option.label}>
                                        {option.label}
                                    </span>
                                    {option.badge && (
                                        <LemonTag type={option.badge.type} size="small">
                                            {option.badge.text}
                                        </LemonTag>
                                    )}
                                    {isSelected && <IconCheckCircle className="text-accent text-sm shrink-0" />}
                                </div>
                                <div className="text-xs text-muted">
                                    {option.description}
                                    {option.learnMoreUrl && (
                                        <>
                                            {' '}
                                            <Link
                                                to={option.learnMoreUrl}
                                                target="_blank"
                                                onClick={(e) => e.stopPropagation()}
                                            >
                                                Learn more
                                            </Link>
                                        </>
                                    )}
                                </div>
                                {option.value === 'group' &&
                                    isSelected &&
                                    value.aggregationGroupTypeIndex != null &&
                                    (groupTypeValues.length > 1 ? (
                                        <div onClick={(e) => e.stopPropagation()}>
                                            <LemonSelect
                                                size="xsmall"
                                                dropdownMatchSelectWidth={false}
                                                data-attr="experiment-bucketing-group-type-select"
                                                value={value.aggregationGroupTypeIndex}
                                                onChange={(v) => {
                                                    if (v != null) {
                                                        onChange({
                                                            option: 'group',
                                                            aggregationGroupTypeIndex: v,
                                                        })
                                                    }
                                                }}
                                                options={groupTypeValues.map((groupType) => ({
                                                    value: groupType.group_type_index,
                                                    label: groupType.group_type,
                                                }))}
                                                disabledReason={disabled ? 'Cannot change while editing' : undefined}
                                            />
                                        </div>
                                    ) : (
                                        <span className="text-xs font-medium">{groupTypeValues[0]?.group_type}</span>
                                    ))}
                            </div>
                        </div>
                    )
                })}
            </div>
        </div>
    )
}

/** Derive the BucketingOption from experiment parameters */
export function bucketingValueFromExperiment(params: {
    aggregation_group_type_index?: number | null
    bucketing_identifier?: string | null
}): BucketingIdentifierValue {
    if (params.aggregation_group_type_index != null) {
        return { option: 'group', aggregationGroupTypeIndex: params.aggregation_group_type_index }
    }
    if (params.bucketing_identifier === 'device_id') {
        return { option: 'device', aggregationGroupTypeIndex: null }
    }
    return { option: 'user', aggregationGroupTypeIndex: null }
}
