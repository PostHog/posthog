import { useActions, useValues } from 'kea'

import { LemonButton, LemonColorButton, LemonModal } from '@posthog/lemon-ui'

import { DataColorToken } from 'lib/colors'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { dataThemeLogic } from 'scenes/dataThemeLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { formatBreakdownLabel } from 'scenes/insights/utils'
import { IndexedTrendResult } from 'scenes/trends/types'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { ResultCustomizationBy } from '~/queries/schema/schema-general'
import { FlattenedFunnelStepByBreakdown } from '~/types'

import { resultCustomizationsModalLogic } from './resultCustomizationsModalLogic'

export function ResultCustomizationsModal(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)

    const { modalVisible, dataset, colorToken, resultCustomizationBy } = useValues(
        resultCustomizationsModalLogic(insightProps)
    )
    const { closeModal, setColorToken, save } = useActions(resultCustomizationsModalLogic(insightProps))

    const { isTrends, isFunnels, querySource } = useValues(insightVizDataLogic)

    const { getTheme } = useValues(dataThemeLogic)
    const theme = getTheme(querySource?.dataColorTheme)

    if (dataset == null || theme == null) {
        return null
    }

    return (
        <LemonModal
            data-attr="legend-entry-modal"
            isOpen={modalVisible}
            title="Customize result color"
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
            {isTrends && (
                <TrendsInfo dataset={dataset as IndexedTrendResult} resultCustomizationBy={resultCustomizationBy} />
            )}
            {isFunnels && <FunnelsInfo dataset={dataset as FlattenedFunnelStepByBreakdown} />}

            <h3 className="l4 mt-2 mb-2">Color</h3>
            <div className="flex flex-wrap gap-1">
                {Object.keys(theme).map((key) => (
                    <LemonColorButton
                        key={key}
                        colorToken={key as DataColorToken}
                        type={key === colorToken ? 'secondary' : 'tertiary'}
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

type TrendsInfoProps = {
    dataset: IndexedTrendResult
    resultCustomizationBy: ResultCustomizationBy
}

function TrendsInfo({ dataset, resultCustomizationBy }: TrendsInfoProps): JSX.Element {
    const { allCohorts } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)
    const { breakdownFilter } = useValues(insightVizDataLogic)

    return (
        <>
            {dataset.breakdown_value ? (
                <p className="mb-2">
                    You are customizing the appearance of series{' '}
                    <b>
                        <EntityFilterInfo filter={dataset.action} allowWrap={true} showSingleName={true} />
                    </b>{' '}
                    for the breakdown{' '}
                    <b>
                        {formatBreakdownLabel(
                            dataset.breakdown_value,
                            breakdownFilter,
                            allCohorts.results,
                            formatPropertyValueForDisplay
                        )}
                    </b>
                    .
                </p>
            ) : (
                <p className="mb-2">
                    You are customizing the appearance of series{' '}
                    <b>
                        <EntityFilterInfo filter={dataset.action} allowWrap={true} showSingleName={true} />
                    </b>
                    .
                </p>
            )}

            <p>
                Results are assigned by{' '}
                {resultCustomizationBy === ResultCustomizationBy.Position ? (
                    <>
                        their <strong>rank</strong> in the dataset
                    </>
                ) : (
                    <>
                        their <strong>name</strong> in the dataset
                    </>
                )}
                . You can change this in insight settings.
            </p>
        </>
    )
}

type FunnelsInfoProps = {
    dataset: FlattenedFunnelStepByBreakdown
}

function FunnelsInfo({ dataset }: FunnelsInfoProps): JSX.Element {
    return (
        <>
            You are customizing the appearance of the{' '}
            {dataset.breakdown_value?.[0] === 'Baseline' ? (
                <b>Baseline</b>
            ) : (
                <>
                    <b>{dataset.breakdown_value?.[0]}</b> breakdown
                </>
            )}
            .
        </>
    )
}
