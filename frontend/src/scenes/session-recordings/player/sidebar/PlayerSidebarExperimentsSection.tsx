import { useActions, useValues } from 'kea'

import { IconExternal, IconWarning } from '@posthog/icons'

import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import type { ExperimentSessionContextItemApi } from 'products/experiments/frontend/generated/api.schemas'

import {
    isControlVariant,
    sessionRecordingExperimentContextLogic,
} from '../player-meta/sessionRecordingExperimentContextLogic'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'

function variantTooltip(item: ExperimentSessionContextItemApi): string {
    return item.multiple_variants
        ? `This session saw multiple variants (${item.variants_seen.join(', ')}) of ${item.experiment_name}. The experiment analysis counts exposure per person, which can differ from a single session.`
        : `This session saw variant "${item.variant}" of ${item.experiment_name}. The experiment analysis counts exposure per person, which can differ from a single session.`
}

function VariantTag({ item }: { item: ExperimentSessionContextItemApi }): JSX.Element {
    const type: LemonTagType = item.multiple_variants ? 'warning' : isControlVariant(item) ? 'muted' : 'highlight'
    return (
        <Tooltip title={variantTooltip(item)}>
            <LemonTag type={type} icon={item.multiple_variants ? <IconWarning /> : undefined} className="shrink-0">
                {item.multiple_variants ? `${item.variants_seen.length} variants` : item.variant}
            </LemonTag>
        </Tooltip>
    )
}

function OpenExperimentButton({ item }: { item: ExperimentSessionContextItemApi }): JSX.Element {
    return (
        <LemonButton
            size="xsmall"
            type="tertiary"
            icon={<IconExternal />}
            to={urls.experiment(item.experiment_id)}
            targetBlank
            hideExternalLinkIcon
            className="shrink-0"
            tooltip="Open experiment in a new tab"
            data-attr="replay-experiment-context-experiment-link"
            onClick={() => {
                void addProductIntentForCrossSell({
                    from: ProductKey.SESSION_REPLAY,
                    to: ProductKey.EXPERIMENTS,
                    intent_context: ProductIntentContext.SESSION_REPLAY_EXPERIMENT_LINK_CLICKED,
                    metadata: { experiment_id: item.experiment_id },
                })
            }}
        />
    )
}

export function PlayerSidebarExperimentsSection(): JSX.Element | null {
    const { logicProps, sessionPlayerData } = useValues(sessionRecordingPlayerLogic)
    const { seekToTimestamp } = useActions(sessionRecordingPlayerLogic)
    const { seenItems, enrolledItems, hasExperimentContext } = useValues(
        sessionRecordingExperimentContextLogic({ sessionRecordingId: logicProps.sessionRecordingId })
    )

    if (!hasExperimentContext) {
        return null
    }

    const recordingStartMs = sessionPlayerData?.start?.valueOf() ?? null
    const recordingEndMs =
        recordingStartMs != null && sessionPlayerData?.durationMs != null
            ? recordingStartMs + sessionPlayerData.durationMs
            : null

    return (
        <div
            className="rounded border bg-surface-primary px-2 py-1 flex flex-col gap-y-1"
            data-attr="replay-experiment-context-overview"
        >
            <h4 className="font-semibold text-xs mb-0">Experiments</h4>

            {seenItems.map((item) => {
                const evaluatedAtMs = item.first_flag_evaluation_timestamp
                    ? dayjs(item.first_flag_evaluation_timestamp).valueOf()
                    : null
                // The backend can return a flag-evaluation timestamp from its ±1h slack around the
                // recording; seeking to an out-of-bounds time silently clamps to a boundary, so only
                // offer the jump when the moment falls inside the playable recording.
                const canSeek =
                    evaluatedAtMs != null &&
                    recordingStartMs != null &&
                    recordingEndMs != null &&
                    evaluatedAtMs >= recordingStartMs &&
                    evaluatedAtMs <= recordingEndMs
                return (
                    <div key={item.experiment_id} className="flex flex-row items-center gap-x-2 min-w-0">
                        {canSeek ? (
                            <Link
                                className="truncate flex-1 min-w-0"
                                title="Jump to when this session matched the experiment's exposure criteria"
                                onClick={() => evaluatedAtMs != null && seekToTimestamp(evaluatedAtMs)}
                                data-attr="replay-experiment-context-jump-to-first-exposure"
                            >
                                {item.experiment_name}
                            </Link>
                        ) : (
                            <span className="truncate flex-1 min-w-0">{item.experiment_name}</span>
                        )}
                        <VariantTag item={item} />
                        <OpenExperimentButton item={item} />
                    </div>
                )
            })}

            {enrolledItems.length > 0 ? (
                <LemonCollapse
                    embedded
                    size="small"
                    panels={[
                        {
                            key: 'enrolled',
                            header: `Also enrolled, carried over (${enrolledItems.length})`,
                            content: (
                                <div className="flex flex-col gap-y-1">
                                    {enrolledItems.map((item) => (
                                        <div
                                            key={item.experiment_id}
                                            className="flex flex-row items-center gap-x-2 min-w-0"
                                        >
                                            <span className="truncate flex-1 min-w-0">{item.experiment_name}</span>
                                            <VariantTag item={item} />
                                            <OpenExperimentButton item={item} />
                                        </div>
                                    ))}
                                </div>
                            ),
                        },
                    ]}
                />
            ) : null}
        </div>
    )
}
