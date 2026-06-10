import { useActions, useValues } from 'kea'
import { useCallback, useRef, useState } from 'react'

import { IconDrag } from '@posthog/icons'
import { LemonCheckbox, LemonLabel, Tooltip } from '@posthog/lemon-ui'

import { capitalizeFirstLetter } from 'lib/utils'
import {
    AGGREGATION_LABEL_FOR_CUSTOM_DATA_WAREHOUSE,
    getAggregationTargetPronoun,
} from 'scenes/insights/filters/aggregationTargetUtils'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { groupsModel, Noun } from '~/models/groupsModel'
import { LifecycleFilter, LifecycleQuery } from '~/queries/schema/schema-general'
import { EditorFilterProps, LifecycleToggle } from '~/types'

const DEFAULT_LIFECYCLE_ORDER: LifecycleToggle[] = ['new', 'returning', 'resurrecting', 'dormant']

const LIFECYCLE_COLORS: Record<LifecycleToggle, string> = {
    new: 'var(--color-lifecycle-new)',
    returning: 'var(--color-lifecycle-returning)',
    resurrecting: 'var(--color-lifecycle-resurrecting)',
    dormant: 'var(--color-lifecycle-dormant)',
}

// Keep for backwards compat with existing usages
const DEFAULT_LIFECYCLE_TOGGLES: LifecycleToggle[] = DEFAULT_LIFECYCLE_ORDER

export function getLifecycleTooltip(
    lifecycle: LifecycleToggle,
    aggregationTargetLabel: Noun,
    aggregationTargetPronoun: 'that' | 'who'
): string {
    switch (lifecycle) {
        case 'new':
            return `${capitalizeFirstLetter(
                aggregationTargetLabel.plural
            )} ${aggregationTargetPronoun} did the event or action during the interval and were also created during that period, e.g. created an account and sent a message today.`
        case 'returning':
            return `${capitalizeFirstLetter(
                aggregationTargetLabel.singular
            )} ${aggregationTargetPronoun} was active in the previous interval and is also active in the current interval, e.g. sent a message yesterday and also sent a message today.`
        case 'resurrecting':
            return `${capitalizeFirstLetter(
                aggregationTargetLabel.singular
            )} ${aggregationTargetPronoun} was not active in the previous interval but became active once again, e.g. did not send any messages for 10 days, but sent one today.`
        case 'dormant':
            return `${capitalizeFirstLetter(
                aggregationTargetLabel.plural
            )} ${aggregationTargetPronoun} are not active in the current interval, but were active in the previous interval, e.g. did not send a message today, but sent one yesterday.`
    }
}

export function LifecycleToggles({ insightProps }: EditorFilterProps): JSX.Element {
    const { insightFilter, aggregationGroupTypeIndex, querySource } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const { aggregationLabel } = useValues(groupsModel)

    const filter = insightFilter as LifecycleFilter
    const toggledLifecycles = filter?.toggledLifecycles || DEFAULT_LIFECYCLE_TOGGLES
    const lifecycleOrdering = filter?.lifecycleOrdering || DEFAULT_LIFECYCLE_ORDER
    const customAggregationTarget = (querySource as LifecycleQuery | null)?.customAggregationTarget === true
    const aggregationTargetLabel = customAggregationTarget
        ? AGGREGATION_LABEL_FOR_CUSTOM_DATA_WAREHOUSE
        : aggregationLabel(aggregationGroupTypeIndex)
    const aggregationTargetPronoun = getAggregationTargetPronoun(aggregationGroupTypeIndex, customAggregationTarget)

    const toggleLifecycle = (name: LifecycleToggle): void => {
        if (toggledLifecycles.includes(name)) {
            updateInsightFilter({ toggledLifecycles: toggledLifecycles.filter((n) => n !== name) })
        } else {
            updateInsightFilter({ toggledLifecycles: [...toggledLifecycles, name] })
        }
    }

    // Drag-to-reorder state
    const dragItem = useRef<number | null>(null)
    const dragOverItem = useRef<number | null>(null)
    const [dragging, setDragging] = useState(false)

    const handleDragStart = useCallback((index: number) => {
        dragItem.current = index
        setDragging(true)
    }, [])

    const handleDragEnter = useCallback((index: number) => {
        dragOverItem.current = index
    }, [])

    const handleDragEnd = useCallback(() => {
        if (dragItem.current !== null && dragOverItem.current !== null && dragItem.current !== dragOverItem.current) {
            const newOrder = [...lifecycleOrdering]
            const [moved] = newOrder.splice(dragItem.current, 1)
            newOrder.splice(dragOverItem.current, 0, moved)
            updateInsightFilter({ lifecycleOrdering: newOrder })
        }
        dragItem.current = null
        dragOverItem.current = null
        setDragging(false)
    }, [lifecycleOrdering, updateInsightFilter])

    return (
        <div className="flex flex-col -mt-1 uppercase">
            {lifecycleOrdering.map((name, index) => (
                <div
                    key={name}
                    className={`flex items-center gap-1 ${dragging ? 'cursor-grabbing' : ''}`}
                    draggable
                    onDragStart={() => handleDragStart(index)}
                    onDragEnter={() => handleDragEnter(index)}
                    onDragEnd={handleDragEnd}
                    onDragOver={(e) => e.preventDefault()}
                >
                    <Tooltip title="Drag to reorder">
                        <span className="cursor-grab text-secondary opacity-50 hover:opacity-100 flex-shrink-0">
                            <IconDrag className="w-3 h-3" />
                        </span>
                    </Tooltip>
                    <LemonLabel info={getLifecycleTooltip(name, aggregationTargetLabel, aggregationTargetPronoun)}>
                        <LemonCheckbox
                            label={name}
                            color={LIFECYCLE_COLORS[name]}
                            checked={toggledLifecycles.includes(name)}
                            onChange={() => toggleLifecycle(name)}
                        />
                    </LemonLabel>
                </div>
            ))}
        </div>
    )
}
