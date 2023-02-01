import { capitalizeFirstLetter, isGroupType, percentage } from 'lib/utils'
import { RetentionTableAppearanceType } from 'scenes/retention/types'
import { dayjs } from 'lib/dayjs'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import './RetentionTable.scss'
import { urls } from 'scenes/urls'
import { groupDisplayId } from 'scenes/persons/GroupActorHeader'
import { asDisplay } from 'scenes/persons/PersonHeader'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { triggerExport } from 'lib/components/ExportButton/exporter'
import { ExporterFormat } from '~/types'
import clsx from 'clsx'
import { MissingPersonsAlert } from 'scenes/trends/persons-modal/PersonsModal'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { retentionLogic } from './retentionLogic'
import { retentionPeopleLogic } from './retentionPeopleLogic'
import { retentionModalLogic } from './retentionModalLogic'

export function RetentionModal(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { results } = useValues(retentionLogic(insightProps))
    const { people, peopleLoading, loadingMore } = useValues(retentionPeopleLogic(insightProps))
    const { loadMorePeople } = useActions(retentionPeopleLogic(insightProps))
    const { aggregationTargetLabel, isVisible, selectedRow } = useValues(retentionModalLogic(insightProps))
    const { closeModal } = useActions(retentionModalLogic(insightProps))

    if (!results) {
        return null
    }

    return (
        <LemonModal
            isOpen={isVisible}
            onClose={closeModal}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeModal}>
                        Close
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() =>
                            triggerExport({
                                export_format: ExporterFormat.CSV,
                                export_context: {
                                    path: results[selectedRow]?.people_url,
                                    max_limit: 10000,
                                },
                            })
                        }
                    >
                        Export to CSV
                    </LemonButton>
                </>
            }
            width={results[selectedRow]?.values[0]?.count === 0 ? undefined : '90%'}
            title={results[selectedRow] ? dayjs(results[selectedRow].date).format('MMMM D, YYYY') : ''}
        >
            {people && !!people.missing_persons && (
                <MissingPersonsAlert actorLabel={aggregationTargetLabel} missingActorsCount={people.missing_persons} />
            )}
            <div className="min-h-20">
                {peopleLoading ? (
                    <SpinnerOverlay />
                ) : results[selectedRow]?.values[0]?.count === 0 ? (
                    <span>No {aggregationTargetLabel.plural} during this period.</span>
                ) : (
                    <>
                        <table className="RetentionTable RetentionTable--non-interactive">
                            <tbody>
                                <tr>
                                    <th>{capitalizeFirstLetter(aggregationTargetLabel.singular)}</th>
                                    {results?.[selectedRow]?.values?.map((data: any, index: number) => (
                                        <th key={index}>
                                            <div>{results[index].label}</div>
                                            <div>
                                                {data.count}
                                                &nbsp;
                                                {data.count > 0 && (
                                                    <span className="text-muted">
                                                        (
                                                        {percentage(
                                                            data.count / results[selectedRow]?.values[0]['count']
                                                        )}
                                                        )
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
                                                        to={urls.person(personAppearances.person.distinct_ids[0])}
                                                        data-attr="retention-person-link"
                                                    >
                                                        {asDisplay(personAppearances.person)}
                                                    </LemonButton>
                                                )}
                                            </td>
                                            {personAppearances.appearances.map((appearance: number, index: number) => {
                                                return (
                                                    <td key={index}>
                                                        <div
                                                            className={clsx('RetentionTable__Tab')}
                                                            style={{
                                                                opacity: appearance ? 1 : 0.2,
                                                                color: appearance ? 'var(--white)' : 'var(--default)',
                                                            }}
                                                        />
                                                    </td>
                                                )
                                            })}
                                        </tr>
                                    ))}
                            </tbody>
                        </table>
                        <div className="m-4 flex justify-center">
                            {people.next ? (
                                <LemonButton type="primary" onClick={loadMorePeople} loading={loadingMore}>
                                    Load more {aggregationTargetLabel.plural}
                                </LemonButton>
                            ) : null}
                        </div>
                    </>
                )}
            </div>
        </LemonModal>
    )
}
