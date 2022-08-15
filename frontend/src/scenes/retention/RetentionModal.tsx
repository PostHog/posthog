import React from 'react'
import { Modal, Button } from 'antd'
import { capitalizeFirstLetter, isGroupType, percentage } from 'lib/utils'
import { Link } from 'lib/components/Link'
import {
    RetentionTablePayload,
    RetentionTablePeoplePayload,
    RetentionTableAppearanceType,
} from 'scenes/retention/types'
import { dayjs } from 'lib/dayjs'
import { Spinner } from 'lib/components/Spinner/Spinner'
import './RetentionTable.scss'
import { urls } from 'scenes/urls'
import { groupDisplayId } from 'scenes/persons/GroupActorHeader'
import { asDisplay } from 'scenes/persons/PersonHeader'
import { LemonButton } from '@posthog/lemon-ui'
import { triggerExport } from 'lib/components/ExportButton/exporter'
import { ExporterFormat } from '~/types'

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
    aggregationTargetLabel: { singular: string; plural: string }
}): JSX.Element | null {
    return (
        <Modal
            visible={visible}
            closable={true}
            onCancel={dismissModal}
            footer={
                <div className="flex justify-between">
                    <div />
                    <div className="flex gap-2">
                        <LemonButton
                            type="secondary"
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
                        <LemonButton type="secondary" onClick={dismissModal}>
                            Close
                        </LemonButton>
                    </div>
                </div>
            }
            style={{
                top: 20,
                minWidth: results[selectedRow]?.values[0]?.count === 0 ? '10%' : '90%',
                fontSize: 16,
            }}
            title={results[selectedRow] ? dayjs(results[selectedRow].date).format('MMMM D, YYYY') : ''}
        >
            {!actorsLoading ? (
                <div>
                    {results[selectedRow]?.values[0]?.count === 0 ? (
                        <span>No {aggregationTargetLabel.plural} during this period.</span>
                    ) : (
                        <div>
                            <table className="table-bordered w-full">
                                <tbody>
                                    <tr>
                                        <th />
                                        {results &&
                                            results
                                                .slice(0, results[selectedRow]?.values.length)
                                                .map((data, index) => <th key={index}>{data.label}</th>)}
                                    </tr>
                                    <tr>
                                        <td>{capitalizeFirstLetter(aggregationTargetLabel.singular)}</td>
                                        {results &&
                                            results[selectedRow]?.values.map((data: any, index: number) => (
                                                <td key={index}>
                                                    {data.count}&nbsp;{' '}
                                                    {data.count > 0 && (
                                                        <span>
                                                            (
                                                            {percentage(
                                                                data.count / results[selectedRow]?.values[0]['count']
                                                            )}
                                                            )
                                                        </span>
                                                    )}
                                                </td>
                                            ))}
                                    </tr>
                                    {actors.result &&
                                        actors.result.map((personAppearances: RetentionTableAppearanceType) => (
                                            <tr key={personAppearances.person.id}>
                                                <td className="text-overflow" style={{ minWidth: 200 }}>
                                                    {isGroupType(personAppearances.person) ? (
                                                        <Link
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
                                                        </Link>
                                                    ) : (
                                                        <Link
                                                            to={urls.person(personAppearances.person.distinct_ids[0])}
                                                            data-attr="retention-person-link"
                                                        >
                                                            {asDisplay(personAppearances.person)}
                                                        </Link>
                                                    )}
                                                </td>
                                                {personAppearances.appearances.map(
                                                    (appearance: number, index: number) => {
                                                        return (
                                                            <td
                                                                key={index}
                                                                className={
                                                                    appearance
                                                                        ? 'retention-success'
                                                                        : 'retention-dropped'
                                                                }
                                                            />
                                                        )
                                                    }
                                                )}
                                            </tr>
                                        ))}
                                </tbody>
                            </table>
                            <div
                                style={{
                                    margin: '1rem',
                                    textAlign: 'center',
                                }}
                            >
                                {actors.next ? (
                                    <Button type="primary" onClick={loadMore} loading={loadingMore}>
                                        Load more {aggregationTargetLabel.plural}
                                    </Button>
                                ) : null}
                            </div>
                        </div>
                    )}
                </div>
            ) : (
                <Spinner size="sm" />
            )}
        </Modal>
    )
}
