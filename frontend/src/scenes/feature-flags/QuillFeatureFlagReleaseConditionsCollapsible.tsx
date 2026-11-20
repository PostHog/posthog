import {
    DndContext,
    DragEndEvent,
    DragStartEvent,
    KeyboardSensor,
    PointerSensor,
    rectIntersection,
    useSensor,
    useSensors,
} from '@dnd-kit/core'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { BindLogic, useActions, useValues } from 'kea'
import React from 'react'
import { v4 as uuidv4 } from 'uuid'

import { IconCollapse, IconExpand, IconPlus } from '@posthog/icons'
import { Button, Item, ItemContent, ItemDescription, Text } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { FeatureFlagGroupType } from '~/types'

import { QuillFractionalRolloutWarning } from 'products/feature_flags/frontend/QuillFractionalRolloutWarning'

import {
    FeatureFlagGroupTypeWithSortKey,
    FeatureFlagReleaseConditionsLogicProps,
    featureFlagReleaseConditionsLogic,
} from './featureFlagReleaseConditionsLogic'
import { QuillFeatureFlagConditionSet } from './QuillFeatureFlagConditionSet'
import { QuillFeatureFlagConditionWarning } from './QuillFeatureFlagConditionWarning'
import { QuillSortableFeatureFlagConditionSet } from './QuillSortableFeatureFlagConditionSet'

interface QuillFeatureFlagReleaseConditionsCollapsibleProps extends Omit<
    FeatureFlagReleaseConditionsLogicProps,
    'readOnly'
> {
    /** Why the person can't save these conditions, shown above them. */
    restrictedReason?: string | null
}

/**
 * The editable release conditions for surfaces that set conditions without a flag, such as the default release
 * conditions setting. It has no read-only mode, match-by options, variant overrides, early exit or flag intent
 * warnings, so the flag editor keeps `FeatureFlagReleaseConditionsCollapsible`.
 */
export function QuillFeatureFlagReleaseConditionsCollapsible({
    id,
    filters,
    onChange,
    restrictedReason,
}: QuillFeatureFlagReleaseConditionsCollapsibleProps): JSX.Element {
    const logicProps = { id, filters, onChange }
    const releaseConditionsLogic = featureFlagReleaseConditionsLogic(logicProps)
    const { filterGroups, openConditions, properties } = useValues(releaseConditionsLogic)
    const { addConditionSet, reorderConditionSets, setOpenConditions, setIsAnyItemDragging, setDraggedGroup } =
        useActions(releaseConditionsLogic)
    const isDragDropEnabled = useFeatureFlag('FEATURE_FLAG_DRAG_DROP_CONDITIONS')

    const sensors = useSensors(
        useSensor(PointerSensor, {
            activationConstraint: { distance: 8 },
        }),
        useSensor(KeyboardSensor)
    )

    const conditionSetsId = id || 'feature-flag-conditions'
    const conditionKeys = filterGroups.map((group: FeatureFlagGroupType) => `condition-${group.sort_key!}`)

    function handleDragStart(event: DragStartEvent): void {
        setIsAnyItemDragging(true)

        const draggedItem = filterGroups.find(
            (group: FeatureFlagGroupType) => group.sort_key === String(event.active.id)
        )
        setDraggedGroup(draggedItem || null)
    }

    function handleDragEnd(event: DragEndEvent): void {
        const { active, over } = event
        if (over && active.id !== over.id) {
            reorderConditionSets(String(active.id), String(over.id))
        }

        setIsAnyItemDragging(false)
        setDraggedGroup(null)
    }

    function handleDragCancel(): void {
        setIsAnyItemDragging(false)
        setDraggedGroup(null)
    }

    const conditionSets = filterGroups.map((group: FeatureFlagGroupType, index: number) => {
        const ConditionSet = isDragDropEnabled ? QuillSortableFeatureFlagConditionSet : QuillFeatureFlagConditionSet

        return (
            <React.Fragment key={`fragment-${group.sort_key!}`}>
                {index > 0 && (
                    <Text size="xs" variant="muted" weight="medium" render={<div className="text-center uppercase" />}>
                        or
                    </Text>
                )}
                <ConditionSet
                    group={group as FeatureFlagGroupTypeWithSortKey}
                    index={index}
                    totalGroups={filterGroups.length}
                    conditionSetsId={conditionSetsId}
                />
            </React.Fragment>
        )
    })

    return (
        <BindLogic logic={featureFlagReleaseConditionsLogic} props={logicProps}>
            <div className="flex flex-col gap-2">
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    Target users for this flag. A condition matches when all property filters pass AND the target falls
                    within the rollout percentage.
                </Text>

                {restrictedReason && (
                    <Item tone="info" size="sm">
                        <ItemContent>
                            <ItemDescription>{restrictedReason}</ItemDescription>
                        </ItemContent>
                    </Item>
                )}

                <QuillFeatureFlagConditionWarning properties={properties} />

                <QuillFractionalRolloutWarning filterGroups={filterGroups} />

                {filterGroups.length > 1 && (
                    <div className="flex flex-wrap justify-end gap-2">
                        {openConditions.length < filterGroups.length && (
                            <Button onClick={() => setOpenConditions(conditionKeys)} data-attr="expand-all-conditions">
                                <IconExpand />
                                Expand all
                            </Button>
                        )}
                        {openConditions.length > 0 && (
                            <Button onClick={() => setOpenConditions([])} data-attr="collapse-all-conditions">
                                <IconCollapse />
                                Collapse all
                            </Button>
                        )}
                    </div>
                )}

                <div className="flex flex-col gap-2">
                    {isDragDropEnabled ? (
                        <DndContext
                            sensors={sensors}
                            collisionDetection={rectIntersection}
                            onDragStart={handleDragStart}
                            onDragEnd={handleDragEnd}
                            onDragCancel={handleDragCancel}
                        >
                            <SortableContext
                                items={filterGroups.map((group: FeatureFlagGroupType) => group.sort_key!)}
                                strategy={verticalListSortingStrategy}
                            >
                                {conditionSets}
                            </SortableContext>
                        </DndContext>
                    ) : (
                        conditionSets
                    )}
                </div>

                <div>
                    <Button variant="outline" onClick={() => addConditionSet(uuidv4())}>
                        <IconPlus />
                        Add condition set
                    </Button>
                </div>
            </div>
        </BindLogic>
    )
}
