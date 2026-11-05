import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, Spinner } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils/strings'

import type { LearningBackfillProgressApi } from '../../generated/api.schemas'
import { businessKnowledgeSettingsLogic } from './businessKnowledgeSettingsLogic'

function progressSummary(progress: LearningBackfillProgressApi): string {
    return `${pluralize(progress.tickets_read, 'ticket')} read, ${progress.knowledge_created} added as knowledge`
}

export function LearnFromPastTicketsSetting(): JSX.Element | null {
    const { settings, learningBackfillStarting } = useValues(businessKnowledgeSettingsLogic)
    const { startLearningBackfill } = useActions(businessKnowledgeSettingsLogic)

    // The Self-learning setting renders this block only after settings load.
    if (!settings) {
        return null
    }

    const progress = settings.learning_backfill ?? null
    const running = progress?.status === 'running'
    const disabledReason = !settings.support_enabled
        ? 'Turn on Support to learn from resolved tickets'
        : !settings.learn_from_support_enabled
          ? 'Turn on Learn from support first'
          : running
            ? 'Already reading past tickets'
            : undefined

    return (
        <div className="flex flex-col items-start gap-2 max-w-xl">
            <div className="flex flex-col gap-1">
                <h4 className="m-0 font-semibold">Learn from past tickets</h4>
                <p className="m-0 text-secondary">
                    Learn from support tickets resolved in the last 90 days, not only from new ones. Tickets that were
                    already read are skipped. PostHog reads them in the background, which can take a few hours.
                </p>
            </div>
            <LemonBanner type="info" className="w-full">
                Knowledge learned from past tickets counts toward your Business knowledge ingestion usage, the same as
                sources you add yourself.
            </LemonBanner>
            {progress && running ? (
                <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2">
                        <Spinner textColored />
                        <span>{`Reading past tickets. Started ${dayjs(progress.started_at).fromNow()}.`}</span>
                    </div>
                    <span className="text-secondary">
                        {`${progressSummary(progress)}, ${progress.tickets_in_progress} being read now.`}
                    </span>
                </div>
            ) : progress?.finished_at ? (
                <span className="text-secondary">
                    {`Read every past ticket ${dayjs(progress.finished_at).fromNow()}: ${progressSummary(progress)}.`}
                </span>
            ) : null}
            <LemonButton
                type="secondary"
                size="small"
                onClick={startLearningBackfill}
                loading={learningBackfillStarting}
                disabledReason={disabledReason}
                // data-attr is a frozen autocapture / Playwright key. Do not rename.
                data-attr="business-knowledge-learn-from-past-tickets"
            >
                Learn from past tickets
            </LemonButton>
        </div>
    )
}
