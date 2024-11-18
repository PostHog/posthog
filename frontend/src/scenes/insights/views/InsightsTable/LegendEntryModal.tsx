import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { InsightLabel } from 'lib/components/InsightLabel'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'
import { hexToRGBA, lightenDarkenColor, RGBToRGBA } from 'lib/utils'
import { dataThemeLogic } from 'scenes/dataThemeLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { getTrendLegendColorToken, getTrendLegendEntryKey } from 'scenes/insights/utils'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { formatCompareLabel } from './columns/SeriesColumn'
import { legendEntryModalLogic } from './legendEntryModalLogic'

export function LegendEntryModal(): JSX.Element | null {
    const { modalVisible, dataset } = useValues(legendEntryModalLogic)
    const { closeModal, setColorToken, save } = useActions(legendEntryModalLogic)

    const { insightProps } = useValues(insightLogic)
    const { colorAssignmentBy, legendEntries } = useValues(trendsDataLogic(insightProps))
    const { updateLegendEntry } = useActions(trendsDataLogic(insightProps))

    const { getTheme } = useValues(dataThemeLogic)
    const { isDarkModeOn } = useValues(themeLogic)

    if (!dataset) {
        return null
    }

    const theme = getTheme('posthog')
    const colorToken = getTrendLegendColorToken(colorAssignmentBy, legendEntries, theme, dataset)
    const legendEntryKey = getTrendLegendEntryKey(colorAssignmentBy, dataset)

    return (
        <LemonModal
            data-attr="legend-entry-modal"
            isOpen={modalVisible}
            title="Customize result data"
            width={520}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={save}>
                        Save customizations
                    </LemonButton>
                </>
            }
            onClose={closeModal}
        >
            <p>
                Query results can be customized to provide a more{' '}
                <strong>meaningful appearance for you and your team members</strong>. The customizations are also shown
                on dashboards.
            </p>
            {dataset != null && (
                <p>
                    You are customizing the display of results for
                    <InsightLabel
                        className="inline-block bg-bg-light px-1 py-0.5 rounded mx-1 border border-dashed"
                        action={dataset?.action}
                        showEventName
                        breakdownValue={dataset.breakdown_value === '' ? 'None' : dataset.breakdown_value?.toString()}
                        hideIcon
                        compareValue={dataset.compare ? formatCompareLabel(dataset) : undefined}
                    />
                    , whereby results are assigned by <strong>position</strong> in the dataset. You can change this in
                    insight settings.
                </p>
            )}
            <div className="l4 mt-2 mb-2">Title</div>
            <div className="l4 mt-2 mb-2">Color</div>
            <div className="flex flex-wrap gap-1">
                {Object.entries(theme).map(([key, color]) => (
                    <LemonButton
                        key={key}
                        type={key === colorToken ? 'secondary' : 'tertiary'}
                        sideIcon={<></>}
                        className="ConditionalFormattingTab__ColorPicker"
                        onClick={(e) => {
                            console.debug('xxx')
                            e.preventDefault()
                            e.stopPropagation()
                            setColorToken(key)
                            updateLegendEntry(legendEntryKey, { color: key })
                        }}
                    >
                        <SeriesGlyph
                            style={{
                                borderColor: color,
                                color: color,
                                backgroundColor: isDarkModeOn
                                    ? RGBToRGBA(lightenDarkenColor(color, -20), 0.3)
                                    : hexToRGBA(color, 0.5),
                            }}
                        >
                            <></>
                        </SeriesGlyph>
                    </LemonButton>
                ))}
            </div>
        </LemonModal>
    )
}
