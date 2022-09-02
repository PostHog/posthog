import React from 'react'
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
            <div className="min-h-20">
                {actorsLoading ? (
                    <SpinnerOverlay />
                ) : results[selectedRow]?.values[0]?.count === 0 ? (
                    <span>No {aggregationTargetLabel.plural} during this period.</span>
                ) : (
                    <>
                        <table className="w-full">
                            <tbody>
                                <tr className="whitespace-nowrap">
                                    <th />
                                    {results &&
                                        results.slice(0, results[selectedRow]?.values.length).map((data, index) => (
                                            <th key={index} className="px-2">
                                                {data.label}
                                            </th>
                                        ))}
                                </tr>
                                <tr className="whitespace-nowrap">
                                    <td className="font-bold pl-2">
                                        {capitalizeFirstLetter(aggregationTargetLabel.singular)}
                                    </td>
                                    {results?.[selectedRow]?.values?.map((data: any, index: number) => (
                                        <td key={index} className="px-2 text-center min-w-6">
                                            {data.count}
                                            {data.count > 0 && (
                                                <span className="text-muted">
                                                    ({percentage(data.count / results[selectedRow]?.values[0]['count'])}
                                                    )
                                                </span>
                                            )}
                                        </td>
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
                                                            className={clsx(
                                                                'rounded-md m-1 h-8',
                                                                appearance ? 'bg-primary-light' : 'bg-primary-highlight'
                                                            )}
                                                        />
                                                    </td>
                                                )
                                            })}
                                        </tr>
                                    ))}
                            </tbody>
                        </table>
                        <div className="m-4 text-center">
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
