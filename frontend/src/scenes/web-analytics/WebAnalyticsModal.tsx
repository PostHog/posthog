import { useActions, useValues } from 'kea'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { ProductIntentContext, addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { urls } from 'scenes/urls'
import { WebQuery } from 'scenes/web-analytics/tiles/WebAnalyticsTile'

import { ProductKey } from '~/types'

import { WebPropertyFilters } from './WebPropertyFilters'
import { ProductTab } from './common'
import { webAnalyticsLogic } from './webAnalyticsLogic'
import { webAnalyticsModalLogic } from './webAnalyticsModalLogic'

export const WebAnalyticsModal = (): JSX.Element | null => {
    const {
        dateFilter: { dateFrom, dateTo },
        productTab,
    } = useValues(webAnalyticsLogic)
    const { modal } = useValues(webAnalyticsModalLogic)

    const { setDates } = useActions(webAnalyticsLogic)
    const { closeModal } = useActions(webAnalyticsModalLogic)

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
            <div className="WebAnalyticsModal deprecated-space-y-4">
                <div className="flex flex-row flex-wrap gap-2">
                    {productTab !== ProductTab.MARKETING && <WebPropertyFilters />}
                    <DateFilter dateFrom={dateFrom} dateTo={dateTo} onChange={setDates} />
                </div>
                <LemonModal.Content embedded>
                    <WebQuery
                        attachTo={webAnalyticsLogic}
                        uniqueKey="WebAnalyticsModal.Query"
                        query={modal.query}
                        insightProps={modal.insightProps}
                        showIntervalSelect={modal.showIntervalSelect}
                        control={modal.control}
                        tileId={modal.tileId}
                    />
                </LemonModal.Content>
                <div className="flex flex-row justify-end">
                    {modal.canOpenInsight ? (
                        <LemonButton
                            to={urls.insightNew({ query: modal.query, sceneSource: 'web-analytics' })}
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
