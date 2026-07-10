import { useActions, useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { sessionRecordingExperimentContextLogic } from '../player-meta/sessionRecordingExperimentContextLogic'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'

export function PlayerSidebarExperimentsSection(): JSX.Element | null {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { seekToTimestamp } = useActions(sessionRecordingPlayerLogic)
    const { experimentItems, hasExperimentContext } = useValues(
        sessionRecordingExperimentContextLogic({ sessionRecordingId: logicProps.sessionRecordingId })
    )

    if (!hasExperimentContext) {
        return null
    }

    return (
        <div
            className="rounded border bg-surface-primary px-2 py-1 flex flex-col gap-y-1"
            data-attr="replay-experiment-context-overview"
        >
            <h4 className="font-semibold text-xs mb-0">Experiments</h4>
            {experimentItems.map((item) => (
                <div key={item.experiment_id} className="flex flex-col gap-y-0.5">
                    <div className="flex flex-row items-center justify-between gap-x-2 min-w-0">
                        <Link
                            to={urls.experiment(item.experiment_id)}
                            className="truncate"
                            data-attr="replay-experiment-context-experiment-link"
                            onClick={() => {
                                void addProductIntentForCrossSell({
                                    from: ProductKey.SESSION_REPLAY,
                                    to: ProductKey.EXPERIMENTS,
                                    intent_context: ProductIntentContext.SESSION_REPLAY_EXPERIMENT_LINK_CLICKED,
                                    metadata: { experiment_id: item.experiment_id },
                                })
                            }}
                        >
                            {item.experiment_name}
                        </Link>
                        <Tooltip
                            title={`This session saw variant "${item.variant}" of ${item.experiment_name}. Flag evaluation — may differ from the experiment's exposure criteria.`}
                        >
                            <LemonTag type={item.multiple_variants ? 'warning' : 'default'}>
                                {item.multiple_variants ? 'saw multiple variants' : item.variant}
                            </LemonTag>
                        </Tooltip>
                    </div>
                    {item.first_flag_evaluation_timestamp ? (
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            onClick={() => seekToTimestamp(dayjs(item.first_flag_evaluation_timestamp).valueOf())}
                            tooltip={`Seeks to when this session first evaluated the flag to "${item.variant}". For experiments with a custom exposure event, the counted exposure may be a later, different event.`}
                            data-attr="replay-experiment-context-jump-to-variant-assignment"
                        >
                            Jump to variant assignment
                        </LemonButton>
                    ) : (
                        <span className="text-secondary text-xs">assignment carried over from an earlier session</span>
                    )}
                </div>
            ))}
        </div>
    )
}
