import './RetentionTable.scss'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { triggerExport } from 'lib/components/ExportButton/exporter'
import { dayjs } from 'lib/dayjs'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { capitalizeFirstLetter, isGroupType, percentage } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { groupDisplayId } from 'scenes/persons/GroupActorDisplay'
import { asDisplay } from 'scenes/persons/person-utils'
import { RetentionTableAppearanceType } from 'scenes/retention/types'
import { MissingPersonsAlert } from 'scenes/trends/persons-modal/PersonsModal'
import { urls } from 'scenes/urls'

import { ExporterFormat } from '~/types'

import { retentionLogic } from './retentionLogic'
import { retentionModalLogic } from './retentionModalLogic'
import { retentionPeopleLogic } from './retentionPeopleLogic'

export function RetentionModal(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { results } = useValues(retentionLogic(insightProps))
    const { people, peopleLoading, peopleLoadingMore, exploreUrl } = useValues(retentionPeopleLogic(insightProps))
    const { loadMorePeople } = useActions(retentionPeopleLogic(insightProps))
    const { aggregationTargetLabel, selectedRow } = useValues(retentionModalLogic(insightProps))
    const { closeModal } = useActions(retentionModalLogic(insightProps))

    if (!results || selectedRow === null) {
        return null
    }

    const row = results[selectedRow]
    const isEmpty = row.values[0]?.count === 0
    return (
        <LemonModal
            isOpen // always open, as we simply don't mount otherwise
            onClose={closeModal}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeModal}>
                        Close
                    </LemonButton>
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
                    <LemonButton
                        type="primary"
                        onClick={() =>
                            void triggerExport({
                                export_format: ExporterFormat.CSV,
                                export_context: {
                                    path: row?.people_url,
                                },
                            })
                        }
                    >
                        Export to CSV
                    </LemonButton>
                </>
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
                                    {row.values?.map((data: any, index: number) => (
                                        <th key={index}>
                                            <div>{results[index].label}</div>
                                            <div>
                                                {data.count}
                                                &nbsp;
                                                {data.count > 0 && (
                                                    <span className="text-muted">
                                                        ({percentage(data.count / row?.values[0]['count'])})
                                                    </span>
                                                )}
                                            </div>
                                        </th>
                                    ))}
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
                        {people.next ? (
                            <div className="m-4 flex justify-center">
                                <LemonButton
                                    type="primary"
                                    onClick={() => loadMorePeople(selectedRow)}
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
