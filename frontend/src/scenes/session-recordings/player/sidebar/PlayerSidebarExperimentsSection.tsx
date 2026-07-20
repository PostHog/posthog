import { useActions, useValues } from 'kea'

import { IconExternal, IconWarning } from '@posthog/icons'

import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { colonDelimitedDuration } from 'lib/utils/durations'
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

const OUT_OF_WINDOW_TOOLTIP =
    "The exposure was captured just outside this recording's playable range, so there's no moment to jump to."

// Position of the exposure within the recording, so the list's chronological order is legible rather than
// implied. Deliberately always relative (not the player's Relative/UTC/device setting like the inspector's
// ItemTimeDisplay): "where in this recording" is the whole point here, and an absolute date would not fit
// the sidebar's width. An exposure captured before the recording starts clamps to zero — the row's tooltip
// is what explains that it landed outside the playable range.
function ExposureTime({ timeInRecording }: { timeInRecording: number }): JSX.Element {
    return (
        <span className="text-secondary text-xs tabular-nums shrink-0 min-w-10 text-right">
            {colonDelimitedDuration(Math.max(0, timeInRecording) / 1000, null)}
        </span>
    )
}

function ExperimentContextRow({
    item,
    onSeek,
    outOfWindow,
    timeInRecording,
}: {
    item: ExperimentSessionContextItemApi
    onSeek?: () => void
    outOfWindow?: boolean
    timeInRecording?: number | null
}): JSX.Element {
    let name: JSX.Element
    if (onSeek) {
        name = (
            <Link
                title="Jump to when this session matched the experiment's exposure criteria"
                onClick={onSeek}
                data-attr="replay-experiment-context-jump-to-first-exposure"
            >
                {item.experiment_name}
            </Link>
        )
    } else if (outOfWindow) {
        name = (
            <Tooltip title={OUT_OF_WINDOW_TOOLTIP}>
                <span>{item.experiment_name}</span>
            </Tooltip>
        )
    } else {
        name = <span>{item.experiment_name}</span>
    }

    // The name lives in its own flex-1 truncate box so the variant tag and open-experiment icon
    // stay right-aligned whether the name is a plain span or a Link (a Link with no `to` renders a
    // button wrapped in a non-flex span, which would otherwise let its tag hug the text).
    return (
        <div className="flex flex-row items-center gap-x-2 min-w-0">
            {timeInRecording != null ? <ExposureTime timeInRecording={timeInRecording} /> : null}
            <div className="flex-1 min-w-0 truncate">{name}</div>
            <VariantTag item={item} />
            <OpenExperimentButton item={item} />
        </div>
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
                const exposedAtMs = item.first_exposure_timestamp
                    ? dayjs(item.first_exposure_timestamp).valueOf()
                    : null
                // The backend can return an exposure timestamp from its ±1h slack around the
                // recording; seeking to an out-of-bounds time silently clamps to a boundary, so only
                // offer the jump when the moment falls inside the playable recording.
                const canSeek =
                    exposedAtMs != null &&
                    recordingStartMs != null &&
                    recordingEndMs != null &&
                    exposedAtMs >= recordingStartMs &&
                    exposedAtMs <= recordingEndMs
                // Distinguish "seen but outside the window" (worth a tooltip) from "bounds not known
                // yet" (transient, no tooltip) so we never explain a non-jump we can't actually vouch for.
                const outOfWindow =
                    exposedAtMs != null &&
                    recordingStartMs != null &&
                    recordingEndMs != null &&
                    (exposedAtMs < recordingStartMs || exposedAtMs > recordingEndMs)
                return (
                    <ExperimentContextRow
                        key={item.experiment_id}
                        item={item}
                        onSeek={canSeek && exposedAtMs != null ? () => seekToTimestamp(exposedAtMs) : undefined}
                        outOfWindow={outOfWindow}
                        timeInRecording={
                            exposedAtMs != null && recordingStartMs != null ? exposedAtMs - recordingStartMs : null
                        }
                    />
                )
            })}

            {enrolledItems.length > 0 ? (
                <LemonCollapse
                    embedded
                    size="small"
                    panels={[
                        {
                            key: 'enrolled',
                            header: `Also enrolled, not exposed in this session (${enrolledItems.length})`,
                            content: (
                                <div className="flex flex-col gap-y-1">
                                    {enrolledItems.map((item) => (
                                        <ExperimentContextRow key={item.experiment_id} item={item} />
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
