import { capitalizeFirstLetter, isGroupType, percentage } from 'lib/utils'
import {
    RetentionTablePayload,
    RetentionTablePeoplePayload,
    RetentionTableAppearanceType,
} from 'scenes/retention/types'
import { dayjs } from 'lib/dayjs'
import { SpinnerOverlay } from 'lib/components/Spinner/Spinner'
import './RetentionTable.scss'
import { urls } from 'scenes/urls'
import { groupDisplayId } from 'scenes/persons/GroupActorHeader'
import { asDisplay } from 'scenes/persons/PersonHeader'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { triggerExport } from 'lib/components/ExportButton/exporter'
import { ExporterFormat } from '~/types'
import clsx from 'clsx'
import { AlertMessage } from 'lib/components/AlertMessage'
import { Noun } from '~/models/groupsModel'

export function RetentionModal({
    results,
    visible,
    selectedRow,
    dismissModal,
    actorsLoading,
    actors,
    loadMore,
    loadingMore,
    aggregationTargetLabel,
}: {
    results: RetentionTablePayload[]
    visible: boolean
    selectedRow: number
    dismissModal: () => void
    loadMore: () => void
    actorsLoading: boolean
    loadingMore: boolean
    actors: RetentionTablePeoplePayload
    aggregationTargetLabel: Noun
}): JSX.Element | null {
    return (
        <LemonModal
            isOpen={visible}
            onClose={dismissModal}
            footer={
                <>
                    <LemonButton type="secondary" onClick={dismissModal}>
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
            {actors && !!actors.missing_persons && (
                <AlertMessage type="info" className="mb-2">
                    {actors.missing_persons}{' '}
                    {actors.missing_persons > 1
                        ? `${aggregationTargetLabel.plural} are`
                        : `${aggregationTargetLabel.singular} is`}{' '}
                    not shown because they've been lost.{' '}
                    <a href="https://posthog.com/docs/how-posthog-works/queries#insights-counting-unique-persons">
                        Read more here for when this can happen
                    </a>
                    .
                </AlertMessage>
            )}
            <div className="min-h-20">
                {actorsLoading ? (
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
                                {actors.result &&
                                    actors.result.map((personAppearances: RetentionTableAppearanceType) => (
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
                            {actors.next ? (
                                <LemonButton type="primary" onClick={loadMore} loading={loadingMore}>
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
