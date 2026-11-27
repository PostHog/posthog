import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import type { ExperimentScoreApi } from '../generated/api.schemas'
import { experimentScoreLabel } from './ExperimentScoreResult'
import { explainMixedScorerVersions, formatItemScorerVersions } from './offlineExperimentPresentation'

export function OfflineExperimentScoreValue({ score }: { score: ExperimentScoreApi }): JSX.Element {
    const label = experimentScoreLabel(score)
    const blockedInputs =
        score.status === 'mixed_versions' ? score.inputs.filter((input) => input.status === 'mixed_versions') : []
    return (
        <Tooltip
            title={
                <div className="max-w-72 space-y-2 text-sm leading-5">
                    <div className="font-semibold">
                        {score.name} · v{score.version}
                    </div>
                    {blockedInputs.length > 0
                        ? blockedInputs.map((input) => <div key={input.alias}>{explainMixedScorerVersions(input)}</div>)
                        : score.inputs.length > 0 && (
                              <dl
                                  aria-label="Item scorers in this run"
                                  className="m-0 grid grid-cols-[fit-content(65%)_1fr] gap-x-4 gap-y-1"
                              >
                                  {score.inputs.map((input) => (
                                      <div key={input.alias} className="contents">
                                          <dt className="break-words">{input.alias}</dt>
                                          <dd className="m-0">{formatItemScorerVersions(input) || 'No results'}</dd>
                                      </div>
                                  ))}
                              </dl>
                          )}
                </div>
            }
        >
            <span className="inline-flex max-w-full flex-col align-middle" tabIndex={0}>
                <span className="inline-flex items-center gap-1 font-medium tabular-nums">
                    <span className="break-words min-w-0">{label}</span>
                    {score.inputs.length > 0 && <IconInfo className="shrink-0 text-muted" aria-label="Score details" />}
                </span>
            </span>
        </Tooltip>
    )
}
