import { useValues } from 'kea'
import { MathTypeGroup } from '~/types'
import {
    apiValueToMathType,
    FunctionAndGroupDynamicMathDefinition,
    FunctionDynamicMathDefinition,
    GroupDynamicMathDefinition,
    MathCategory,
    mathsLogic,
    MATH_TYPE_GROUP_DEFINITIONS,
    SELECTABLE_MATH_DEFINITIONS,
    StaticMathDefinition,
} from 'scenes/trends/mathsLogic'
import { LemonSelect, LemonSelectOption, LemonSelectOptions } from '@posthog/lemon-ui'
import { useState } from 'react'
import { GroupIntroductionFooter } from 'scenes/groups/GroupsIntroduction'
import { groupsModel } from '~/models/groupsModel'

export enum MathAvailability {
    All,
    ActorsOnly,
    None,
}

interface MathSelectorProps {
    math?: string
    mathGroupTypeIndex?: number | null
    mathAvailability: MathAvailability
    index: number
    onMathSelect: (index: number, value: any) => any
    style?: React.CSSProperties
}

function DynamicLabel({
    mathTypeGroup,
    subMathShown,
    groupTypeShownIndex,
    index,
    onFunctionSelect,
    onGroupTypeSelect,
    definition,
}: {
    mathTypeGroup: MathTypeGroup
    index: number
    definition: FunctionDynamicMathDefinition | GroupDynamicMathDefinition | FunctionAndGroupDynamicMathDefinition
    subMathShown: string
    groupTypeShownIndex: number
    onFunctionSelect: (subMath: string) => void
    onGroupTypeSelect: (groupTypeIndex: number) => void
}): JSX.Element {
    const { groupTypes, aggregationLabel } = useValues(groupsModel)

    return (
        <definition.Label
            functionSelector={
                definition.functionDynamic ? (
                    <LemonSelect
                        value={subMathShown}
                        onSelect={onFunctionSelect}
                        options={Object.entries(
                            MATH_TYPE_GROUP_DEFINITIONS[mathTypeGroup] as Record<string, StaticMathDefinition>
                        ).map(([key, subDefinition]) => ({
                            value: key,
                            label: subDefinition.shortName,
                            tooltip: subDefinition.description,
                            'data-attr': `math-${apiValueToMathType(key, groupTypeShownIndex)}-${index}`,
                        }))}
                        onClick={(e) => e.stopPropagation()}
                        size="small"
                        dropdownMatchSelectWidth={false}
                        optionTooltipPlacement="right"
                    />
                ) : (
                    // TS should know that only functionSelector is only needed with functionDynamic
                    (undefined as unknown as JSX.Element)
                )
            }
            groupTypeSelector={
                definition.groupDynamic ? (
                    <LemonSelect
                        value={groupTypeShownIndex}
                        onSelect={onGroupTypeSelect}
                        options={groupTypes.map((groupType) => ({
                            value: groupType.group_type_index,
                            label: aggregationLabel(groupType.group_type_index).singular,
                            'data-attr': `math-${apiValueToMathType(
                                subMathShown,
                                groupType.group_type_index
                            )}-${index}`,
                        }))}
                        onClick={(e) => e.stopPropagation()}
                        size="small"
                        dropdownMatchSelectWidth={false}
                        optionTooltipPlacement="right"
                    />
                ) : (
                    // TS should know that only groupTypeSelector is only needed with groupDynamic
                    (undefined as unknown as JSX.Element)
                )
            }
        />
    )
}

function useMathSelectorOptions({
    math,
    mathGroupTypeIndex,
    mathAvailability,
    index,
    onMathSelect,
}: MathSelectorProps): LemonSelectOptions<string> {
    const { needsUpgradeForGroups, canStartUsingGroups } = useValues(mathsLogic)

    const [subMathsShown, setSubMathsShown] = useState<Partial<Record<MathTypeGroup, string>>>(
        Object.fromEntries(
            Object.entries(SELECTABLE_MATH_DEFINITIONS)
                .filter(([, definition]) => definition.functionDynamic)
                .map(([key, definition]) => [
                    key,
                    math && math in MATH_TYPE_GROUP_DEFINITIONS[key]
                        ? math
                        : (definition as FunctionDynamicMathDefinition).defaultOption,
                ])
        )
    )
    const [groupTypeShown, setGroupTypeShown] = useState<number>(mathGroupTypeIndex ?? 0)

    const options: LemonSelectOption<string>[] = Object.entries(SELECTABLE_MATH_DEFINITIONS)
        .filter(
            mathAvailability === MathAvailability.ActorsOnly
                ? ([, definition]) => definition.category === MathCategory.ActorCount
                : () => true
        )
        .map(([key, definition]) => ({
            value: definition.functionDynamic
                ? apiValueToMathType(subMathsShown[key], groupTypeShown)
                : apiValueToMathType(key, groupTypeShown),
            label:
                definition.groupDynamic || definition.functionDynamic ? (
                    <DynamicLabel
                        mathTypeGroup={key as MathTypeGroup}
                        index={index}
                        definition={definition}
                        subMathShown={definition.functionDynamic ? subMathsShown[key] : key}
                        groupTypeShownIndex={groupTypeShown}
                        onFunctionSelect={(value) => {
                            setSubMathsShown((state) => ({ ...state, [key]: value }))
                            onMathSelect(index, apiValueToMathType(value, groupTypeShown))
                        }}
                        onGroupTypeSelect={(value) => {
                            setGroupTypeShown(value)
                            onMathSelect(
                                index,
                                apiValueToMathType(definition.functionDynamic ? subMathsShown[key] : key, value)
                            )
                        }}
                    />
                ) : (
                    definition.name
                ),
            tooltip: definition.description,
            'data-attr': `math-${definition.groupDynamic || definition.functionDynamic ? 'node-' : ''}${key}-${index}`,
        }))

    return [
        {
            options,
            footer:
                needsUpgradeForGroups || canStartUsingGroups ? (
                    <GroupIntroductionFooter needsUpgrade={needsUpgradeForGroups} />
                ) : undefined,
        },
    ]
}

export function MathSelector({
    math,
    mathGroupTypeIndex,
    mathAvailability,
    index,
    onMathSelect,
}: MathSelectorProps): JSX.Element {
    const options = useMathSelectorOptions({
        math,
        mathGroupTypeIndex,
        mathAvailability,
        index,
        onMathSelect,
    })

    const mathType = apiValueToMathType(math, mathGroupTypeIndex)

    return (
        <LemonSelect
            value={mathType}
            options={options}
            onChange={(value) => onMathSelect(index, value)}
            data-attr={`math-selector-${index}`}
            optionTooltipPlacement="right"
            dropdownMatchSelectWidth={false}
            dropdownPlacement="bottom-start"
        />
    )
}
