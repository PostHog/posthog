import './LegendEntryModal.scss'

import { LemonButton, LemonButtonProps, LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DataColorToken } from 'lib/colors'
import { InsightLabel } from 'lib/components/InsightLabel'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'
import { hexToRGBA, lightenDarkenColor, RGBToRGBA } from 'lib/utils'
import { dataThemeLogic } from 'scenes/dataThemeLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { formatCompareLabel } from './columns/SeriesColumn'
import { legendEntryModalLogic } from './legendEntryModalLogic'

export function LegendEntryModal(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)

    const { modalVisible, dataset, colorToken } = useValues(legendEntryModalLogic(insightProps))
    const { closeModal, setColorToken, save } = useActions(legendEntryModalLogic(insightProps))

    const { getTheme } = useValues(dataThemeLogic)

    if (!dataset) {
        return null
    }

    const theme = getTheme('posthog')

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
            <h3 className="l4 mt-2 mb-2">Color</h3>
            <div className="flex flex-wrap gap-1">
                {Object.keys(theme).map((key) => (
                    <ColorGlyphButton
                        key={key as DataColorToken}
                        colorToken={key as DataColorToken}
                        selected={key === colorToken}
                        onClick={(e) => {
                            e.preventDefault()
                            e.stopPropagation()

                            setColorToken(key as DataColorToken)
                        }}
                    />
                ))}
            </div>
        </LemonModal>
    )
}

type ColorGlyphButtonProps = {
    colorToken: DataColorToken
    selected: boolean
    onClick: LemonButtonProps['onClick']
}

function ColorGlyphButton({ colorToken, selected, onClick }: ColorGlyphButtonProps): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    const { getTheme } = useValues(dataThemeLogic)

    const theme = getTheme('posthog')
    const color = theme[colorToken]

    return (
        <LemonButton
            type={selected ? 'secondary' : 'tertiary'}
            className="LegendEntryModal__ColorGlyphButton"
            onClick={onClick}
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
    )
}
