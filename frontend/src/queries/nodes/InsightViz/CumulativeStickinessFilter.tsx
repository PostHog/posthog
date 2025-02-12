import { LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { EditorFilterProps } from '~/types'

export function CumulativeStickinessFilter({ insightProps }: EditorFilterProps): JSX.Element {
    const { stickinessFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <LemonSwitch
            data-attr="cumulative-stickiness-toggle"
            onChange={(checked) => {
                updateInsightFilter({
                    cumulative: checked,
                })
            }}
            checked={!!stickinessFilter?.cumulative}
            label="Show cumulative values"
        />
    )
}
