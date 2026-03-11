import { useActions, useValues } from 'kea'

import { LemonCheckbox, LemonLabel } from '@posthog/lemon-ui'

import { capitalizeFirstLetter } from 'lib/utils'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { groupsModel, Noun } from '~/models/groupsModel'
import { LifecycleFilter } from '~/queries/schema/schema-general'
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
    aggregationGroupTypeIndex?: number | null
): string {
    const subjectPronoun = aggregationGroupTypeIndex != null ? 'that' : 'who'

    switch (lifecycle) {
        case 'new':
            return `${capitalizeFirstLetter(
                aggregationTargetLabel.plural
            )} ${subjectPronoun} did the event or action during the interval and were also created during that period, e.g. created an account and sent a message today.`
        case 'returning':
            return `${capitalizeFirstLetter(
                aggregationTargetLabel.singular
            )} ${subjectPronoun} was active in the previous interval and is also active in the current interval, e.g. sent a message yesterday and also sent a message today.`
        case 'resurrecting':
            return `${capitalizeFirstLetter(
                aggregationTargetLabel.singular
            )} ${subjectPronoun} was not active in the previous interval but became active once again, e.g. did not send any messages for 10 days, but sent one today.`
        case 'dormant':
            return `${capitalizeFirstLetter(
                aggregationTargetLabel.plural
            )} ${subjectPronoun} are not active in the current interval, but were active in the previous interval, e.g. did not send a message today, but sent one yesterday.`
    }
}

export function LifecycleToggles({ insightProps }: EditorFilterProps): JSX.Element {
    const { insightFilter, aggregationGroupTypeIndex } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const { aggregationLabel } = useValues(groupsModel)

    const toggledLifecycles = (insightFilter as LifecycleFilter)?.toggledLifecycles || DEFAULT_LIFECYCLE_TOGGLES
    const aggregationTargetLabel = aggregationLabel(aggregationGroupTypeIndex)

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
                    info={getLifecycleTooltip(lifecycle.name, aggregationTargetLabel, aggregationGroupTypeIndex)}
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
