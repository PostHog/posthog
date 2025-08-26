import './RetentionTable.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { capitalizeFirstLetter, isGroupType, percentage } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { groupDisplayId } from 'scenes/persons/GroupActorDisplay'
import { asDisplay } from 'scenes/persons/person-utils'
import { RetentionTableAppearanceType } from 'scenes/retention/types'
import { MissingPersonsAlert } from 'scenes/trends/persons-modal/PersonsModal'
import { SaveCohortModal } from 'scenes/trends/persons-modal/SaveCohortModal'
import { urls } from 'scenes/urls'

import { MAX_SELECT_RETURNED_ROWS, startDownload } from '~/queries/nodes/DataTable/DataTableExport'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { ExporterFormat } from '~/types'

import { retentionLogic } from './retentionLogic'
import { retentionModalLogic } from './retentionModalLogic'
import { retentionPeopleLogic } from './retentionPeopleLogic'

export function RetentionModal(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { results } = useValues(retentionLogic(insightProps))
    const { people, peopleLoading, peopleLoadingMore } = useValues(retentionPeopleLogic(insightProps))
    const { loadMorePeople } = useActions(retentionPeopleLogic(insightProps))
    const {
        aggregationTargetLabel,
        selectedInterval,
        selectedBreakdownValue,
        exploreUrl,
        insightEventsQueryUrl,
        actorsQuery,
        isCohortModalOpen,
    } = useValues(retentionModalLogic(insightProps))
    const { theme } = useValues(retentionModalLogic(insightProps))
    const { closeModal, saveAsCohort, setIsCohortModalOpen } = useActions(retentionModalLogic(insightProps))
    const { startExport } = useActions(exportsLogic)

    const backgroundColor = theme?.['preset-1'] || '#000000' // Default to black if no color found
    const dataTableNodeQuery: DataTableNode | undefined = actorsQuery
        ? {
              kind: NodeKind.DataTableNode,
              source: actorsQuery,
          }
        : undefined

    if (!results || selectedInterval === null) {
        return null
    }

    // Find the correct row based on both selectedInterval and selectedBreakdownValue
    const row =
        selectedBreakdownValue !== null
            ? (() => {
                  // Get the target date from the selected interval in the non-breakdown results
                  const targetLabel = results[selectedInterval]?.label
                  // Find the row with matching breakdown value and date label
                  return (
                      results.find((r) => r.breakdown_value === selectedBreakdownValue && r.label === targetLabel) ||
                      results[selectedInterval]
                  )
              })()
            : results[selectedInterval]
    const rowLength = row.values.length
    const isEmpty = row.values[0]?.count === 0

    return (
        <>
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
                            {!!people.result?.length && !people.result.some((person) => isGroupType(person.person)) && (
                                <LemonButton
                                    onClick={() => setIsCohortModalOpen(true)}
                                    type="secondary"
                                    data-attr="retention-person-modal-save-as-cohort"
                                    disabled={!people.result?.length}
                                >
                                    Save as cohort
                                </LemonButton>
                            )}
                        </div>
                        <div className="flex gap-2">
                            {insightEventsQueryUrl && (
                                <LemonButton
                                    type="secondary"
                                    to={insightEventsQueryUrl}
                                    data-attr="person-modal-view-events"
                                    onClick={() => {
                                        closeModal()
                                    }}
                                    targetBlank
                                >
                                    View events
                                </LemonButton>
                            )}
                            {exploreUrl && (
                                <LemonButton
                                    type="primary"
                                    to={exploreUrl}
                                    data-attr="person-modal-new-insight"
                                    onClick={() => {
                                        closeModal()
                                    }}
                                >
                                    Open as new insight
                                </LemonButton>
                            )}
                        </div>
                    </div>
                }
                width={isEmpty ? undefined : '90%'}
                title={`${row.date.format('MMMM D, YYYY')} Cohort`}
            >
                {people && !!people.missing_persons && (
                    <MissingPersonsAlert
                        actorLabel={aggregationTargetLabel}
                        missingActorsCount={people.missing_persons}
                    />
                )}
                <div>
                    {peopleLoading ? (
                        <SpinnerOverlay />
                    ) : isEmpty ? (
                        <span>No {aggregationTargetLabel.plural} during this period.</span>
                    ) : (
                        <>
                            <table
                                className="RetentionTable RetentionTable--non-interactive"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={
                                    {
                                        '--retention-table-color': backgroundColor,
                                    } as React.CSSProperties
                                }
                            >
                                <tbody>
                                    <tr>
                                        <th>{capitalizeFirstLetter(aggregationTargetLabel.singular)}</th>
                                        {row.values?.map((data: any, index: number) => {
                                            return (
                                                <th key={index}>
                                                    <div>{data.label}</div>
                                                    <div>
                                                        {data.count}
                                                        &nbsp;
                                                        {data.count > 0 && (
                                                            <span className="text-secondary">
                                                                ({percentage(data.count / row?.values[0]['count'])})
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
                                                <td className="min-w-[200px]">
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
                                                                personAppearances.person.distinct_ids?.[0]
                                                            )}
                                                            data-attr="retention-person-link"
                                                        >
                                                            {asDisplay(personAppearances.person)}
                                                        </LemonButton>
                                                    )}
                                                </td>

                                                {personAppearances.appearances
                                                    // Only show the number of appearances as the lookahead we have (without going into future)
                                                    .slice(0, rowLength)
                                                    .map((appearance: number, index: number) => {
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
                                        onClick={() => loadMorePeople(selectedInterval, selectedBreakdownValue)}
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
            <SaveCohortModal
                onSave={(title) => saveAsCohort(title)}
                onCancel={() => setIsCohortModalOpen(false)}
                isOpen={isCohortModalOpen}
            />
        </>
    )
}
