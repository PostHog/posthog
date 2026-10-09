import { useActions, useValues } from 'kea'

import { urls } from 'scenes/urls'

import type { TodayReportPreview } from '~/layout/today/todayPreviewCards'
import { TodayPreviewTrigger } from '~/layout/today/TodayPreviewTrigger'

import { SignalReport } from 'products/signals/frontend/inbox/types'
import { displayConventionalCommitTitle } from 'products/signals/frontend/inbox/utils/reportPresentation'

import { itemStateLabel } from './todayBriefingItems'
import { TodayIcon } from './TodayIcon'
import { TodayReportOpenSource, todayLogic } from './todayLogic'
import { TodayNavItem } from './TodayNavItem'
import { reportIcon, reportMeta, reportSource } from './todaySignalReports'

interface TodayReportNavItemProps {
    report: SignalReport
    preview: TodayReportPreview
    source: Extract<TodayReportOpenSource, 'sidebar' | 'sidebar_more'>
    dataAttr: string
}

export function TodayReportNavItem({ report, preview, source, dataAttr }: TodayReportNavItemProps): JSX.Element {
    const { reportId, hoveredReportId, reportStateOverrides } = useValues(todayLogic)
    const { reportOpened, setHoveredReportId } = useActions(todayLogic)
    const override = reportStateOverrides[report.id]

    return (
        <TodayPreviewTrigger payload={preview}>
            <TodayNavItem
                title={displayConventionalCommitTitle(report.title, 'Untitled report')}
                meta={itemStateLabel({ state: override ?? 'open' }) ?? reportMeta(report)}
                color={reportSource(report).color}
                icon={<TodayIcon icon={reportIcon(report)} />}
                to={urls.todayReport(report.id)}
                active={hoveredReportId === report.id}
                current={reportId === report.id}
                state={override}
                dataAttr={dataAttr}
                onClick={() => reportOpened(report, source)}
                onHoverChange={(hovered) => setHoveredReportId(hovered ? report.id : null)}
            />
        </TodayPreviewTrigger>
    )
}
