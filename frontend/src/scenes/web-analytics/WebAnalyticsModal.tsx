import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'
import { WebQuery } from 'scenes/web-analytics/WebAnalyticsTile'
import { WebPropertyFilters } from 'scenes/web-analytics/WebPropertyFilters'

export const WebAnalyticsModal = (): JSX.Element | null => {
    const {
        modal,
        dateFilter: { dateFrom, dateTo },
        webAnalyticsFilters,
    } = useValues(webAnalyticsLogic)
    const { closeModal, setDates, setWebAnalyticsFilters } = useActions(webAnalyticsLogic)

    if (!modal) {
        return null
    }

    return (
        <LemonModal
            isOpen={!!modal}
            onClose={closeModal}
            simple
            title={modal?.title || ''}
            width={1600}
            fullScreen={false}
            closable={true}
        >
            <div className="flex flex-row flex-wrap gap-2">
                <WebPropertyFilters
                    setWebAnalyticsFilters={setWebAnalyticsFilters}
                    webAnalyticsFilters={webAnalyticsFilters}
                />
                <DateFilter dateFrom={dateFrom} dateTo={dateTo} onChange={setDates} />
            </div>
            <header>header</header>
            <LemonModal.Content embedded>
                <WebQuery
                    query={modal.query}
                    insightProps={modal.insightProps}
                    showIntervalSelect={modal.showIntervalSelect}
                />
            </LemonModal.Content>
        </LemonModal>
    )
}
