import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { addProductIntentForCrossSell, ProductIntentContext } from 'lib/utils/product-intents'
import { urls } from 'scenes/urls'
import { WebQuery } from 'scenes/web-analytics/tiles/WebAnalyticsTile'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'
import { WebPropertyFilters } from 'scenes/web-analytics/WebPropertyFilters'

import { ProductKey } from '~/types'

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
            simple={false}
            title={modal?.title || ''}
            width={1600}
            fullScreen={false}
            closable={true}
        >
            <div className="WebAnalyticsModal space-y-4">
                <div className="flex flex-row flex-wrap gap-2">
                    <WebPropertyFilters
                        setWebAnalyticsFilters={setWebAnalyticsFilters}
                        webAnalyticsFilters={webAnalyticsFilters}
                    />
                    <DateFilter dateFrom={dateFrom} dateTo={dateTo} onChange={setDates} />
                </div>
                <LemonModal.Content embedded>
                    <WebQuery
                        query={modal.query}
                        insightProps={modal.insightProps}
                        showIntervalSelect={modal.showIntervalSelect}
                        control={modal.control}
                    />
                </LemonModal.Content>
                <div className="flex flex-row justify-end">
                    {modal.canOpenInsight ? (
                        <LemonButton
                            to={urls.insightNew({ query: modal.query })}
                            icon={<IconOpenInNew />}
                            size="small"
                            type="secondary"
                            onClick={() => {
                                void addProductIntentForCrossSell({
                                    from: ProductKey.WEB_ANALYTICS,
                                    to: ProductKey.PRODUCT_ANALYTICS,
                                    intent_context: ProductIntentContext.WEB_ANALYTICS_INSIGHT,
                                })
                            }}
                        >
                            Open as new Insight
                        </LemonButton>
                    ) : null}
                </div>
            </div>
        </LemonModal>
    )
}
