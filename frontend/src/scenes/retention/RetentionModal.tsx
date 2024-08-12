import './RetentionTable.scss'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { dayjs } from 'lib/dayjs'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { capitalizeFirstLetter, isGroupType, percentage } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { groupDisplayId } from 'scenes/persons/GroupActorDisplay'
import { asDisplay } from 'scenes/persons/person-utils'
import { RetentionTableAppearanceType } from 'scenes/retention/types'
import { MissingPersonsAlert } from 'scenes/trends/persons-modal/PersonsModal'
import { urls } from 'scenes/urls'

import { MAX_SELECT_RETURNED_ROWS, startDownload } from '~/queries/nodes/DataTable/DataTableExport'
import { DataTableNode, NodeKind } from '~/queries/schema'
import { ExporterFormat } from '~/types'

import { retentionLogic } from './retentionLogic'
import { retentionModalLogic } from './retentionModalLogic'
import { retentionPeopleLogic } from './retentionPeopleLogic'

export function RetentionModal(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { results } = useValues(retentionLogic(insightProps))
    const { people, peopleLoading, peopleLoadingMore } = useValues(retentionPeopleLogic(insightProps))
    const { loadMorePeople } = useActions(retentionPeopleLogic(insightProps))
    const { aggregationTargetLabel, selectedInterval, exploreUrl, actorsQuery, retentionFilter } = useValues(
        retentionModalLogic(insightProps)
    )
    const { closeModal } = useActions(retentionModalLogic(insightProps))
    const { startExport } = useActions(exportsLogic)

    const dataTableNodeQuery: DataTableNode | undefined = actorsQuery
        ? {
              kind: NodeKind.DataTableNode,
              source: actorsQuery,
          }
        : undefined

    if (!results || selectedInterval === null) {
        return null
    }

    const row = results[selectedInterval]
    const isEmpty = row.values[0]?.count === 0
    return (
        <LemonModal
            isOpen // always open, as we simply don't mount otherwise
            onClose={closeModal}
            footer={
                <div className="flex justify-between gap-2 w-full">
                    <div className="flex gap-2">
                        {!!people.result?.length && !exploreUrl && (
                            <LemonButton
                                type="secondary"
                                onClick={() =>
                                    startExport({
                                        export_format: ExporterFormat.CSV,
                                        export_context: {
                                            path: row?.people_url,
                                        },
                                    })
                                }
                            >
                                Download CSV
                            </LemonButton>
                        )}
                        {!!people.result?.length && !!dataTableNodeQuery && (
                            <LemonButton
                                type="secondary"
                                onClick={() => {
                                    dataTableNodeQuery && void startDownload(dataTableNodeQuery, true, startExport)
                                }}
                                tooltip={`Up to ${MAX_SELECT_RETURNED_ROWS} persons will be exported`}
                            >
                                Export all as CSV
                            </LemonButton>
                        )}
                    </div>
                    {exploreUrl && (
                        <LemonButton
                            type="primary"
                            to={exploreUrl}
                            data-attr="person-modal-new-insight"
                            onClick={() => {
                                closeModal()
                            }}
                        >
                            Explore
                        </LemonButton>
                    )}
                </div>
            }
            width={isEmpty ? undefined : '90%'}
            title={`${dayjs(row.date).format('MMMM D, YYYY')} Cohort`}
        >
            {people && !!people.missing_persons && (
                <MissingPersonsAlert actorLabel={aggregationTargetLabel} missingActorsCount={people.missing_persons} />
            )}
            <div>
                {peopleLoading ? (
                    <SpinnerOverlay />
                ) : isEmpty ? (
                    <span>No {aggregationTargetLabel.plural} during this period.</span>
                ) : (
                    <>
                        <table className="RetentionTable RetentionTable--non-interactive">
                            <tbody>
                                <tr>
                                    <th>{capitalizeFirstLetter(aggregationTargetLabel.singular)}</th>
                                    {row.values?.map((data: any, index: number) => {
                                        let cumulativeCount = data.count
                                        if (retentionFilter?.cumulative) {
                                            for (let i = index + 1; i < row.values.length; i++) {
                                                cumulativeCount += row.values[i].count
                                            }
                                            cumulativeCount = Math.min(cumulativeCount, row.values[0].count)
                                        }
                                        const percentageValue =
                                            row.values[0].count > 0 ? cumulativeCount / row.values[0].count : 0

                                        return (
                                            <th key={index}>
                                                <div>{results[index].label}</div>
                                                <div>
                                                    {cumulativeCount}
                                                    &nbsp;
                                                    {cumulativeCount > 0 && (
                                                        <span className="text-muted">
                                                            ({percentage(percentageValue)})
                                                        </span>
                                                    )}
                                                </div>
                                            </th>
                                        )
                                    })}
                                </tr>
                                {people.result &&
                                    people.result.map((personAppearances: RetentionTableAppearanceType) => (
                                        <tr key={personAppearances.person.id}>
                                            {/* eslint-disable-next-line react/forbid-dom-props */}
                                            <td style={{ minWidth: 200 }}>
                                                {isGroupType(personAppearances.person) ? (
                                                    <LemonButton
                                                        size="small"
                                                        to={urls.group(
                                                            String(personAppearances.person.group_type_index),
                                                            personAppearances.person.group_key
                                                        )}
                                                        data-attr="retention-person-link"
                                                    >
                                                        {groupDisplayId(
                                                            personAppearances.person.group_key,
                                                            personAppearances.person.properties
                                                        )}
                                                    </LemonButton>
                                                ) : (
                                                    <LemonButton
                                                        size="small"
                                                        to={urls.personByDistinctId(
                                                            personAppearances.person.distinct_ids[0]
                                                        )}
                                                        data-attr="retention-person-link"
                                                    >
                                                        {asDisplay(personAppearances.person)}
                                                    </LemonButton>
                                                )}
                                            </td>
                                            {personAppearances.appearances.map((appearance: number, index: number) => {
                                                const hasAppearance = !!appearance
                                                return (
                                                    <td key={index}>
                                                        <div
                                                            className={clsx(
                                                                'RetentionTable__Tab',
                                                                hasAppearance ? 'opacity-100' : 'opacity-20'
                                                            )}
                                                        />
                                                    </td>
                                                )
                                            })}
                                        </tr>
                                    ))}
                            </tbody>
                        </table>
                        {people.next || people.offset ? (
                            <div className="m-4 flex justify-center">
                                <LemonButton
                                    type="primary"
                                    onClick={() => loadMorePeople(selectedInterval)}
                                    loading={peopleLoadingMore}
                                >
                                    Load more {aggregationTargetLabel.plural}
                                </LemonButton>
                            </div>
                        ) : null}
                    </>
                )}
            </div>
        </LemonModal>
    )
}
