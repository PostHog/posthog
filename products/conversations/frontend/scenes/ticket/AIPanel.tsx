import { IconX } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import {
    type AITriage,
    type KnowledgeGapSuggestion,
    aiTriageResultLabel,
    aiTriageResultTagType,
    aiTriageTicketTypeDescription,
    aiTriageTicketTypeLabel,
} from '../../types'

interface AIPanelProps {
    aiTriage?: AITriage
    knowledgeGaps?: KnowledgeGapSuggestion[]
    knowledgeGapsLoading?: boolean
    onDismissGap?: (suggestionId: string) => void
}

function AITriageHeaderTag({ aiTriage }: { aiTriage?: AITriage }): JSX.Element | null {
    if (!aiTriage?.status) {
        return null
    }
    if (aiTriage.status === 'in_progress') {
        return <Spinner className="text-sm ml-1" />
    }
    if (aiTriage.result) {
        return (
            <LemonTag type={aiTriageResultTagType(aiTriage.result)} size="small" className="ml-1">
                {aiTriageResultLabel[aiTriage.result]}
            </LemonTag>
        )
    }
    return null
}

export function AIPanel({ aiTriage, knowledgeGaps, knowledgeGapsLoading, onDismissGap }: AIPanelProps): JSX.Element {
    const hasData = aiTriage && aiTriage.status
    const pendingGaps = knowledgeGaps?.filter((g) => g.status === 'pending') ?? []

    return (
        <LemonCollapse
            className="bg-surface-primary"
            panels={[
                {
                    key: 'ai_triage',
                    header: (
                        <span className="flex items-center">
                            AI triage
                            <AITriageHeaderTag aiTriage={aiTriage} />
                        </span>
                    ),
                    content: hasData ? (
                        <div className="space-y-2 text-xs">
                            {aiTriage.status && (
                                <div className="flex justify-between">
                                    <span className="text-muted-alt">Status</span>
                                    <span className="capitalize">
                                        {aiTriage.status === 'in_progress' ? 'In progress' : aiTriage.status}
                                    </span>
                                </div>
                            )}
                            {aiTriage.result && (
                                <div className="flex justify-between">
                                    <span className="text-muted-alt">Result</span>
                                    <LemonTag type={aiTriageResultTagType(aiTriage.result)} size="small">
                                        {aiTriageResultLabel[aiTriage.result]}
                                    </LemonTag>
                                </div>
                            )}
                            {aiTriage.ticket_type && (
                                <div className="flex justify-between">
                                    <span className="text-muted-alt">Ticket type</span>
                                    <Tooltip title={aiTriageTicketTypeDescription[aiTriage.ticket_type]}>
                                        <LemonTag size="small">
                                            {aiTriageTicketTypeLabel[aiTriage.ticket_type] ?? aiTriage.ticket_type}
                                        </LemonTag>
                                    </Tooltip>
                                </div>
                            )}
                            {aiTriage.confidence != null && (
                                <div className="flex justify-between">
                                    <span className="text-muted-alt">Confidence</span>
                                    <span>{(aiTriage.confidence * 100).toFixed(0)}%</span>
                                </div>
                            )}
                            {aiTriage.attempts != null && (
                                <div className="flex justify-between">
                                    <span className="text-muted-alt">Attempts</span>
                                    <span>{aiTriage.attempts}</span>
                                </div>
                            )}
                            {aiTriage.needs_diagnostics != null && (
                                <div className="flex justify-between">
                                    <span className="text-muted-alt">Needs diagnostics</span>
                                    <span>{aiTriage.needs_diagnostics ? 'Yes' : 'No'}</span>
                                </div>
                            )}
                            {aiTriage.diagnostics_allowed != null && (
                                <div className="flex justify-between">
                                    <span className="text-muted-alt">Diagnostics allowed</span>
                                    <span>{aiTriage.diagnostics_allowed ? 'Yes' : 'No'}</span>
                                </div>
                            )}
                            {aiTriage.started_at && (
                                <div className="flex justify-between">
                                    <span className="text-muted-alt">Started</span>
                                    <TZLabel time={aiTriage.started_at} />
                                </div>
                            )}
                            {aiTriage.finished_at && (
                                <div className="flex justify-between">
                                    <span className="text-muted-alt">Finished</span>
                                    <TZLabel time={aiTriage.finished_at} />
                                </div>
                            )}
                        </div>
                    ) : (
                        <div className="text-muted-alt text-xs">AI has not processed this ticket yet.</div>
                    ),
                },
                ...(pendingGaps.length > 0 || knowledgeGapsLoading
                    ? [
                          {
                              key: 'knowledge_gaps',
                              header: (
                                  <span className="flex items-center gap-1">
                                      Knowledge gaps
                                      {pendingGaps.length > 0 && (
                                          <LemonTag type="highlight" size="small">
                                              {pendingGaps.length}
                                          </LemonTag>
                                      )}
                                  </span>
                              ),
                              content: knowledgeGapsLoading ? (
                                  <Spinner className="text-sm" />
                              ) : (
                                  <div className="space-y-2 text-xs">
                                      <p className="text-muted-alt">
                                          Topics the AI couldn't cover from{' '}
                                          <Link to={urls.businessKnowledge()}>Business knowledge</Link>.
                                      </p>
                                      {pendingGaps.map((gap) => (
                                          <div key={gap.id} className="flex items-start justify-between gap-1 py-0.5">
                                              <span className="flex-1 break-words">{gap.topic}</span>
                                              {onDismissGap && (
                                                  <LemonButton
                                                      size="xsmall"
                                                      icon={<IconX />}
                                                      tooltip="Dismiss"
                                                      noPadding
                                                      onClick={() => onDismissGap(gap.id)}
                                                  />
                                              )}
                                          </div>
                                      ))}
                                      <Link to={urls.businessKnowledge()} className="text-xs">
                                          Manage in Business knowledge
                                      </Link>
                                  </div>
                              ),
                          },
                      ]
                    : []),
            ]}
        />
    )
}
