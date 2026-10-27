import { useActions, useValues } from 'kea'

import { IconLightBulb } from '@posthog/icons'
import {
    Button,
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
    Field,
    FieldDescription,
    FieldLabel,
    Input,
    Text,
} from '@posthog/quill'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { TodayRow } from 'scenes/project-homepage/today/TodayRow'
import { urls } from 'scenes/urls'

import type { BetsDetailApi, BetsWorkApi } from '../generated/api.schemas'
import {
    IDEA_ICON_COLOR,
    SHOWN_EVIDENCE,
    buildCost,
    hasMoreReport,
    ideaEvidence,
    ideaReason,
    ideaReportRest,
    ideaStatus,
} from '../lib/ideas'
import type { BetWorkStatus } from '../lib/workStatus'
import { betLogic } from '../logics/betLogic'
import { BetEvidenceChip } from './BetEvidenceChip'
import { BetWorkStatusIcon } from './BetWorkStatusIcon'

const ASSESSMENT_MARKS: Record<string, BetWorkStatus['mark']> = {
    supported: 'verified',
    pending: 'spinner',
    not_supported: 'neutral',
}

export function BetIdeaRow({ item, bet }: { item: BetsWorkApi; bet: BetsDetailApi }): JSX.Element {
    const {
        busy,
        busyOperation,
        buildDisabledReason,
        dismissingIdea,
        dismissReason,
        expandedIdeas,
        openIdea,
        allEvidenceShown,
        ideaInProgress,
    } = useValues(betLogic({ id: bet.id }))
    const {
        buildIdea,
        dismissIdea,
        openDismiss,
        setDismissReason,
        toggleIdeaReport,
        setExpandedIdea,
        showAllEvidence,
    } = useActions(betLogic({ id: bet.id }))
    const status = ideaStatus(item)
    const reason =
        ideaReason(item) || (item.assessment === 'pending' ? 'The Scout checks this idea against your data.' : '')
    const evidence = ideaEvidence(item)
    const shownEvidence = allEvidenceShown.includes(item.id) ? evidence : evidence.slice(0, SHOWN_EVIDENCE)
    const hiddenEvidence = evidence.length - shownEvidence.length
    const expanded = openIdea === item.id
    const dismissing = dismissingIdea === item.id
    const reportOpen = expandedIdeas.includes(item.id)
    const supported = item.assessment === 'supported'
    const building = busyOperation === `work:${item.id}:build`
    const dismissBusy = busyOperation === `work:${item.id}:dismiss`
    const reasonId = `bets-idea-dismiss-${item.id}`
    const buildButton = (
        <Button
            size="sm"
            variant={supported ? 'primary' : 'outline'}
            loading={building}
            disabled={busy && !building}
            disabledReason={buildDisabledReason ?? undefined}
            onClick={() => buildIdea(item.id)}
            data-attr="bets-idea-build"
        >
            {item.assessment === 'not_supported' ? 'Build anyway' : 'Build this idea'}
        </Button>
    )
    return (
        <TodayRow
            tone="neutral"
            icon={{ color: IDEA_ICON_COLOR, glyph: <IconLightBulb /> }}
            title={item.title}
            facts={status.filter(Boolean)}
            statusIcon={
                ASSESSMENT_MARKS[item.assessment] ? (
                    <BetWorkStatusIcon status={{ label: status[1], mark: ASSESSMENT_MARKS[item.assessment] }} />
                ) : undefined
            }
            actions={bet.is_owner && !ideaInProgress ? buildButton : undefined}
            expansion={{
                expanded,
                onToggle: () => setExpandedIdea(expanded ? null : item.id),
                triggerDataAttr: 'bets-idea-toggle',
                detail: (
                    <div className="TodayRow__detailBody min-w-0 pb-2">
                        {reason && (
                            <Text size="sm" render={<p className="m-0 max-w-prose leading-relaxed" />}>
                                {reason}
                            </Text>
                        )}
                        {item.moves_metric && (
                            <Text size="sm" variant="muted" render={<p className="m-0" />}>
                                Moves: {item.moves_metric}
                            </Text>
                        )}
                        {evidence.length > 0 && (
                            <div className="flex min-w-0 flex-wrap gap-2">
                                {shownEvidence.map((entry, index) => (
                                    <BetEvidenceChip key={`${entry.url}-${index}`} evidence={entry} />
                                ))}
                                {hiddenEvidence > 0 && (
                                    <button
                                        type="button"
                                        className="Bets__evidence Bets__evidence--more inline-flex h-7 min-w-0 items-center gap-1.5"
                                        onClick={() => showAllEvidence(item.id)}
                                        data-attr="bets-idea-evidence-more"
                                    >
                                        +{hiddenEvidence} more
                                    </button>
                                )}
                            </div>
                        )}
                        {(hasMoreReport(item) || item.report_id) && (
                            <Collapsible
                                variant="folder"
                                open={reportOpen}
                                onOpenChange={() => toggleIdeaReport(item.id)}
                            >
                                <CollapsibleTrigger className="Bets__ideaToggle" data-attr="bets-idea-report">
                                    {reportOpen ? 'Hide the report' : 'Read the report'}
                                </CollapsibleTrigger>
                                <CollapsibleContent className="px-0 pb-0">
                                    <div className="flex max-w-prose flex-col gap-2 pt-1">
                                        {hasMoreReport(item) && (
                                            <LemonMarkdown
                                                className="Bets__taskFindings"
                                                lowKeyHeadings
                                                disableImages="all"
                                                disableMentions
                                            >
                                                {ideaReportRest(item)}
                                            </LemonMarkdown>
                                        )}
                                        {item.report_id && (
                                            <Button
                                                size="inline"
                                                variant="link"
                                                className="self-start"
                                                render={
                                                    <LinkPrimitive to={urls.inboxReport('reports', item.report_id)} />
                                                }
                                                data-attr="bets-idea-open-report"
                                            >
                                                Open the full report
                                            </Button>
                                        )}
                                    </div>
                                </CollapsibleContent>
                            </Collapsible>
                        )}
                        {bet.is_owner &&
                            (dismissing ? (
                                <form
                                    className="flex flex-col gap-3"
                                    onSubmit={(event) => {
                                        event.preventDefault()
                                        if (dismissReason.trim()) {
                                            dismissIdea(item.id, dismissReason)
                                        }
                                    }}
                                    onKeyDown={(event) => {
                                        if (event.key === 'Escape') {
                                            openDismiss(null)
                                        }
                                    }}
                                >
                                    <Field>
                                        <FieldLabel htmlFor={reasonId}>Why dismiss this idea?</FieldLabel>
                                        <Input
                                            id={reasonId}
                                            autoFocus
                                            maxLength={1000}
                                            value={dismissReason}
                                            onChange={(event) => setDismissReason(event.target.value)}
                                            placeholder="For example, we tried this last quarter"
                                        />
                                        <FieldDescription>
                                            The Scout reads this before it looks for new ideas.
                                        </FieldDescription>
                                    </Field>
                                    <div className="flex flex-wrap items-center gap-2">
                                        <Button
                                            type="submit"
                                            size="sm"
                                            variant="primary"
                                            loading={dismissBusy}
                                            disabled={busy && !dismissBusy}
                                            disabledReason={dismissReason.trim() ? undefined : 'Add a reason first.'}
                                            data-attr="bets-idea-dismiss-confirm"
                                        >
                                            Dismiss idea
                                        </Button>
                                        <Button
                                            type="button"
                                            size="sm"
                                            variant="link-muted"
                                            disabled={dismissBusy}
                                            onClick={() => openDismiss(null)}
                                            data-attr="bets-idea-dismiss-cancel"
                                        >
                                            Cancel
                                        </Button>
                                    </div>
                                </form>
                            ) : (
                                <div className="flex flex-wrap items-center gap-2">
                                    {buildButton}
                                    <Button
                                        size="sm"
                                        variant="link-muted"
                                        disabled={busy}
                                        onClick={() => openDismiss(item.id)}
                                        data-attr="bets-idea-dismiss"
                                    >
                                        Dismiss
                                    </Button>
                                    <Text size="xs" variant="muted" render={<span className="ps-1" />}>
                                        {buildCost(bet)}
                                    </Text>
                                </div>
                            ))}
                    </div>
                ),
            }}
            dataAttr="bets-idea"
        />
    )
}
