import { useActions, useValues } from 'kea'

import type { BriefingItemApi } from 'products/today/frontend/generated/api.schemas'

import { itemHref, itemReportId, itemStateLabel } from './todayBriefingItems'
import { todayLogic } from './todayLogic'
import { priorityTone } from './todayPriority'
import { TodayReportRowDetail } from './TodayReportRowDetail'
import { TodayRow } from './TodayRow'
import { pullRequestFact, rowFacts } from './todayRowFacts'
import { briefingItemIcon } from './todayRowIcons'
import { reportTitle } from './todaySignalReports'
import { TodayVerdictButtons } from './TodayVerdictButtons'
import type { TodayReportVerdictTarget } from './todayVerdictLogic'

const SOURCE_LABELS: Record<BriefingItemApi['source'], string> = {
    self_driving: 'Report',
    product_analytics: 'Dashboard',
    alerts: 'Alert',
    support: 'Ticket',
    error_tracking: 'Issue',
    github: 'Pull request',
}

function withoutPriority(signal: string): string {
    const rest = signal.replace(/^P\d,\s*/, '')
    return rest.charAt(0).toUpperCase() + rest.slice(1)
}

export function TodayBriefingItemRow({ item, done }: { item: BriefingItemApi; done: boolean }): JSX.Element {
    const { reportPreviews, expandedReportRows } = useValues(todayLogic)
    const { itemOpened, toggleReportRow } = useActions(todayLogic)
    const priority = item.report ? item.report.priority : 'P2'
    const kind = item.report ? null : item.group === 'dashboard' ? 'Dashboard' : SOURCE_LABELS[item.source]
    const reportId = itemReportId(item)
    const preview = reportPreviews[item.key]
    const to = itemHref(item)
    const title = item.report ? reportTitle(item) : item.title
    const target: TodayReportVerdictTarget | null = reportId
        ? {
              reportId,
              title,
              hasOpenPullRequest:
                  !!item.report?.pull_request_url &&
                  item.report.pull_request_state !== 'closed' &&
                  item.report.pull_request_state !== 'merged',
          }
        : null
    return (
        <TodayRow
            tone={priorityTone(priority)}
            icon={briefingItemIcon(item)}
            title={title}
            label={priority ?? undefined}
            facts={
                done
                    ? rowFacts([itemStateLabel(item)])
                    : rowFacts([kind, withoutPriority(item.signal), pullRequestFact(item.report?.pull_request_state)])
            }
            to={to}
            onOpen={() => itemOpened(item)}
            expansion={
                preview && target
                    ? {
                          expanded: !!expandedReportRows[item.key],
                          onToggle: () => toggleReportRow(item.key, target.reportId),
                          detail: (
                              <TodayReportRowDetail
                                  preview={preview}
                                  to={to}
                                  onOpen={() => itemOpened(item)}
                                  actions={done ? null : <TodayVerdictButtons target={target} labelled />}
                                  dataAttr="today-list-briefing-item"
                              />
                          ),
                      }
                    : undefined
            }
            actions={target ? <TodayVerdictButtons target={target} /> : undefined}
            done={done}
            reportId={reportId ?? undefined}
            dataAttr="today-list-briefing-item"
        />
    )
}
