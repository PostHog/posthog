import { IconCopy, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonSelect } from '@posthog/lemon-ui'
import { useState } from 'react'

import {
    AlertDetectorsConfig,
    DetectorConfigType,
    DetectorGroup,
    DetectorType,
    FilterLogicalOperator,
} from '~/queries/schema/schema-general'
import { FilterLogicalOperator as FLO } from '~/types'

import { createDefaultKMeansConfig, KMeansDetectorForm } from './KMeansDetectorForm'
import { createDefaultThresholdConfig, ThresholdDetectorForm } from './ThresholdDetectorForm'
import { createDefaultZScoreConfig, ZScoreDetectorForm } from './ZScoreDetectorForm'

export interface DetectorBuilderProps {
    config: AlertDetectorsConfig | null
    onChange: (config: AlertDetectorsConfig) => void
}

type DetectorOrGroup = DetectorConfigType | DetectorGroup

function isDetectorGroup(item: DetectorOrGroup): item is DetectorGroup {
    return 'detectors' in item && Array.isArray(item.detectors)
}

function getDetectorTypeName(type: DetectorType | string): string {
    switch (type) {
        case DetectorType.THRESHOLD:
        case 'threshold':
            return 'Threshold'
        case DetectorType.ZSCORE:
        case 'zscore':
            return 'Z-Score'
        case DetectorType.KMEANS:
        case 'kmeans':
            return 'K-Means'
        default:
            return 'Unknown'
    }
}

function createDefaultDetector(type: DetectorType): DetectorConfigType {
    switch (type) {
        case DetectorType.THRESHOLD:
            return createDefaultThresholdConfig()
        case DetectorType.ZSCORE:
            return createDefaultZScoreConfig()
        case DetectorType.KMEANS:
            return createDefaultKMeansConfig()
    }
}

interface SingleDetectorFormProps {
    config: DetectorConfigType
    onChange: (config: DetectorConfigType) => void
    onRemove: () => void
    onDuplicate: () => void
    canRemove: boolean
}

function SingleDetectorForm({
    config,
    onChange,
    onRemove,
    onDuplicate,
    canRemove,
}: SingleDetectorFormProps): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(true)

    return (
        <div className="border rounded p-3 bg-bg-light">
            <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                    <LemonSelect
                        value={config.type}
                        onChange={(value) => {
                            if (value !== config.type) {
                                onChange(createDefaultDetector(value as DetectorType))
                            }
                        }}
                        options={[
                            { value: DetectorType.THRESHOLD, label: 'Threshold' },
                            { value: DetectorType.ZSCORE, label: 'Z-Score' },
                            { value: DetectorType.KMEANS, label: 'K-Means' },
                        ]}
                        size="small"
                    />
                    <LemonButton size="xsmall" onClick={() => setIsExpanded(!isExpanded)}>
                        {isExpanded ? 'Collapse' : 'Expand'}
                    </LemonButton>
                </div>
                <div className="flex items-center gap-1">
                    <LemonButton icon={<IconCopy />} size="xsmall" onClick={onDuplicate} tooltip="Duplicate" />
                    <LemonButton
                        icon={<IconTrash />}
                        size="xsmall"
                        onClick={onRemove}
                        disabled={!canRemove}
                        tooltip="Remove"
                        status="danger"
                    />
                </div>
            </div>

            {isExpanded && (
                <div className="mt-3">
                    {(config.type === DetectorType.THRESHOLD || config.type === 'threshold') && (
                        <ThresholdDetectorForm config={config as any} onChange={onChange as any} />
                    )}
                    {(config.type === DetectorType.ZSCORE || config.type === 'zscore') && (
                        <ZScoreDetectorForm config={config as any} onChange={onChange as any} />
                    )}
                    {(config.type === DetectorType.KMEANS || config.type === 'kmeans') && (
                        <KMeansDetectorForm config={config as any} onChange={onChange as any} />
                    )}
                </div>
            )}
        </div>
    )
}

interface DetectorGroupFormProps {
    group: DetectorGroup
    onChange: (group: DetectorGroup) => void
    onRemove: () => void
    depth: number
}

function DetectorGroupForm({ group, onChange, onRemove, depth }: DetectorGroupFormProps): JSX.Element {
    const updateDetector = (index: number, newConfig: DetectorOrGroup): void => {
        const newDetectors = [...group.detectors]
        newDetectors[index] = newConfig
        onChange({ ...group, detectors: newDetectors })
    }

    const removeDetector = (index: number): void => {
        const newDetectors = group.detectors.filter((_, i) => i !== index)
        onChange({ ...group, detectors: newDetectors })
    }

    const duplicateDetector = (index: number): void => {
        const newDetectors = [...group.detectors]
        newDetectors.splice(index + 1, 0, JSON.parse(JSON.stringify(group.detectors[index])))
        onChange({ ...group, detectors: newDetectors })
    }

    const addDetector = (): void => {
        onChange({
            ...group,
            detectors: [...group.detectors, createDefaultThresholdConfig()],
        })
    }

    const addNestedGroup = (): void => {
        const nestedGroup: DetectorGroup = {
            type: group.type === FilterLogicalOperator.AND_ ? FilterLogicalOperator.OR_ : FilterLogicalOperator.AND_,
            detectors: [createDefaultThresholdConfig()],
        }
        onChange({
            ...group,
            detectors: [...group.detectors, nestedGroup],
        })
    }

    const operatorLabel = group.type === FilterLogicalOperator.AND_ || group.type === FLO.And ? 'AND' : 'OR'

    return (
        <div className={`border-l-2 ${depth > 0 ? 'ml-4 pl-3 border-border' : 'pl-0 border-transparent'}`}>
            {group.detectors.map((item, index) => (
                <div key={index}>
                    {index > 0 && (
                        <div className="flex items-center gap-2 my-2">
                            <LemonDivider className="flex-1" />
                            <LemonSelect
                                value={group.type}
                                onChange={(value) =>
                                    onChange({
                                        ...group,
                                        type: value as FilterLogicalOperator,
                                    })
                                }
                                options={[
                                    { value: FilterLogicalOperator.AND_, label: 'AND' },
                                    { value: FilterLogicalOperator.OR_, label: 'OR' },
                                ]}
                                size="xsmall"
                                className="font-bold"
                            />
                            <LemonDivider className="flex-1" />
                        </div>
                    )}

                    {isDetectorGroup(item) ? (
                        <DetectorGroupForm
                            group={item}
                            onChange={(newGroup) => updateDetector(index, newGroup)}
                            onRemove={() => removeDetector(index)}
                            depth={depth + 1}
                        />
                    ) : (
                        <SingleDetectorForm
                            config={item}
                            onChange={(newConfig) => updateDetector(index, newConfig)}
                            onRemove={() => removeDetector(index)}
                            onDuplicate={() => duplicateDetector(index)}
                            canRemove={group.detectors.length > 1}
                        />
                    )}
                </div>
            ))}

            <div className="flex gap-2 mt-3">
                <LemonButton icon={<IconPlus />} size="small" onClick={addDetector}>
                    Add detector
                </LemonButton>
                {depth < 2 && (
                    <LemonButton icon={<IconPlus />} size="small" onClick={addNestedGroup} type="secondary">
                        Add {operatorLabel === 'AND' ? 'OR' : 'AND'} group
                    </LemonButton>
                )}
                {depth > 0 && (
                    <LemonButton icon={<IconTrash />} size="small" onClick={onRemove} status="danger" type="secondary">
                        Remove group
                    </LemonButton>
                )}
            </div>
        </div>
    )
}

export function DetectorBuilder({ config, onChange }: DetectorBuilderProps): JSX.Element {
    const currentConfig: AlertDetectorsConfig = config || {
        type: FilterLogicalOperator.AND_,
        groups: [createDefaultThresholdConfig()],
    }

    const handleGroupChange = (newGroups: DetectorOrGroup[]): void => {
        onChange({
            ...currentConfig,
            groups: newGroups,
        })
    }

    // Wrap in a DetectorGroup for easier handling
    const wrappedGroup: DetectorGroup = {
        type: currentConfig.type,
        detectors: currentConfig.groups,
    }

    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between">
                <h4 className="font-semibold">Alert detectors</h4>
                <div className="flex items-center gap-2 text-sm">
                    <span className="text-muted">Top-level logic:</span>
                    <LemonSelect
                        value={currentConfig.type}
                        onChange={(value) =>
                            onChange({
                                ...currentConfig,
                                type: value as FilterLogicalOperator,
                            })
                        }
                        options={[
                            { value: FilterLogicalOperator.AND_, label: 'All match (AND)' },
                            { value: FilterLogicalOperator.OR_, label: 'Any match (OR)' },
                        ]}
                        size="small"
                    />
                </div>
            </div>

            <DetectorGroupForm
                group={wrappedGroup}
                onChange={(newGroup) => handleGroupChange(newGroup.detectors)}
                onRemove={() => {}}
                depth={0}
            />
        </div>
    )
}

export function createDefaultDetectorsConfig(): AlertDetectorsConfig {
    return {
        type: FilterLogicalOperator.AND_,
        groups: [createDefaultThresholdConfig()],
    }
}
