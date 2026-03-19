import { useActions, useValues } from 'kea'

import { LemonCheckbox, LemonLabel } from '@posthog/lemon-ui'

import { capitalizeFirstLetter } from 'lib/utils'
import {
    AGGREGATION_LABEL_FOR_CUSTOM_DATA_WAREHOUSE,
    getAggregationTargetPronoun,
} from 'scenes/insights/filters/aggregationTargetUtils'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { groupsModel, Noun } from '~/models/groupsModel'
import { LifecycleFilter, LifecycleQuery } from '~/queries/schema/schema-general'
import { EditorFilterProps, LifecycleToggle } from '~/types'

const lifecycles: { name: LifecycleToggle; color: string }[] = [
    {
        name: 'new',
        color: 'var(--color-lifecycle-new)',
    },
    {
        name: 'returning',
        color: 'var(--color-lifecycle-returning)',
    },
    {
        name: 'resurrecting',
        color: 'var(--color-lifecycle-resurrecting)',
    },
    {
        name: 'dormant',
        color: 'var(--color-lifecycle-dormant)',
    },
]

const DEFAULT_LIFECYCLE_TOGGLES: LifecycleToggle[] = ['new', 'returning', 'resurrecting', 'dormant']

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

    const toggledLifecycles = (insightFilter as LifecycleFilter)?.toggledLifecycles || DEFAULT_LIFECYCLE_TOGGLES
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

    return (
        <div className="flex flex-col -mt-1 uppercase">
            {lifecycles.map((lifecycle) => (
                <LemonLabel
                    key={lifecycle.name}
                    info={getLifecycleTooltip(lifecycle.name, aggregationTargetLabel, aggregationTargetPronoun)}
                >
                    <LemonCheckbox
                        label={lifecycle.name}
                        color={lifecycle.color}
                        checked={toggledLifecycles.includes(lifecycle.name)}
                        onChange={() => toggleLifecycle(lifecycle.name)}
                    />
                </LemonLabel>
            ))}
        </div>
    )
}
