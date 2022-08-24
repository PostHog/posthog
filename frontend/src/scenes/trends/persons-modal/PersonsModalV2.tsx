import React, { useState } from 'react'
import { useActions, useValues } from 'kea'
import { DownloadOutlined } from '@ant-design/icons'
import { ActorType, ExporterFormat } from '~/types'
import { personsModalLogic } from './personsModalV2Logic'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { isGroupType, midEllipsis } from 'lib/utils'
import './PersonsModal.scss'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { GroupActorHeader } from 'scenes/persons/GroupActorHeader'
import { IconPersonFilled, IconSave } from 'lib/components/icons'
import { MultiRecordingButton } from 'scenes/session-recordings/multiRecordingButton/multiRecordingButton'
import { triggerExport } from 'lib/components/ExportButton/exporter'
import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'
import { PersonHeader } from 'scenes/persons/PersonHeader'
import ReactDOM from 'react-dom'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { openSaveCohortModal } from './SaveCohortModalV2'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

export interface PersonsModalProps {
    onAfterClose?: () => void
    url: string
    title: React.ReactNode
}

function PersonsModalV2({ url, title, onAfterClose }: PersonsModalProps): JSX.Element {
    const [isOpen, setIsOpen] = useState(true)
    const logic = personsModalLogic({ url, closeModal: () => setIsOpen(false) })

    const { allPeople, peopleLoading, people: peopleRes, searchTerm } = useValues(logic)
    const { loadPeople, setSearchTerm, saveCohortWithUrl } = useActions(logic)

    const onSaveCohort = (): void => {
        openSaveCohortModal({
            onSave: (title) => {
                saveCohortWithUrl(title)
            },
        })
    }

    // const showCountedByTag = !!people?.crossDataset?.find(({ action }) => action?.math && action.math !== 'total')
    // const hasMultipleSeries = !!people?.crossDataset?.find(({ action }) => action?.order)

    return (
        <>
            {/* {!!sessionRecordingId && <SessionPlayerDrawer onClose={closeRecordingModal} />} */}
            <LemonModal
                title={title}
                isOpen={isOpen}
                onClose={() => setIsOpen(false)}
                onAfterClose={onAfterClose}
                description={
                    <>
                        <LemonInput
                            type="search"
                            placeholder="Search for persons by email, name, or ID"
                            fullWidth
                            value={searchTerm}
                            onChange={setSearchTerm}
                            className="my-2"
                        />
                        <div className="flex items-center gap-2 text-muted">
                            {peopleLoading ? (
                                <>
                                    <Spinner size="sm" />
                                    <span>Loading...</span>
                                </>
                            ) : (
                                <>
                                    <IconPersonFilled className="text-xl" />
                                    <span>
                                        This list contains {peopleRes?.next ? 'more than ' : ''}
                                        <b>{peopleRes?.results.length} unique results</b>
                                    </span>
                                </>
                            )}
                        </div>
                    </>
                }
                footer={
                    <>
                        {
                            <LemonButton
                                onClick={onSaveCohort}
                                icon={<IconSave />}
                                type="secondary"
                                data-attr="person-modal-save-as-cohort"
                            >
                                Save as cohort
                            </LemonButton>
                        }
                        <LemonButton
                            icon={<DownloadOutlined />}
                            type="secondary"
                            onClick={() => {
                                triggerExport({
                                    export_format: ExporterFormat.CSV,
                                    export_context: {
                                        path: url,
                                    },
                                })
                            }}
                            data-attr="person-modal-download-csv"
                        >
                            Download CSV
                        </LemonButton>
                    </>
                }
                width={600}
            >
                <div className="relative min-h-20" style={{ margin: '0 -1.5rem' }}>
                    {allPeople && allPeople.length > 0 ? (
                        <LemonTable
                            columns={
                                [
                                    {
                                        title: 'Person',
                                        key: 'person',
                                        render: function Render(_, actor: ActorType) {
                                            return <ActorRow actor={actor} />
                                        },
                                    },
                                    {
                                        width: 0,
                                        title: 'Recordings',
                                        key: 'recordings',
                                        render: function Render(_, actor: ActorType) {
                                            if (
                                                actor.matched_recordings?.length &&
                                                actor.matched_recordings?.length > 0
                                            ) {
                                                return (
                                                    <MultiRecordingButton
                                                        sessionRecordings={actor.matched_recordings}
                                                        onOpenRecording={(sessionRecording) => {
                                                            console.log(sessionRecording)
                                                            // openRecordingModal(sessionRecording.session_id)
                                                        }}
                                                    />
                                                )
                                            }
                                        },
                                    },
                                ] as LemonTableColumns<ActorType>
                            }
                            className="persons-table"
                            rowKey="id"
                            expandable={{
                                expandedRowRender: function RenderPropertiesTable({ properties }) {
                                    return Object.keys(properties).length ? (
                                        <PropertiesTable properties={properties} />
                                    ) : (
                                        'This person has no properties.'
                                    )
                                },
                            }}
                            embedded
                            showHeader={false}
                            dataSource={allPeople}
                            nouns={['person', 'persons']}
                        />
                    ) : peopleRes ? (
                        <div className="person-row-container person-row">
                            We couldn't find any matching results for this data point.
                        </div>
                    ) : null}
                </div>

                {peopleRes?.next && (
                    <div className="m-4 flex justify-center">
                        <LemonButton
                            type="primary"
                            onClick={() => peopleRes?.next && loadPeople({ url: peopleRes?.next })}
                            loading={peopleLoading}
                        >
                            Load more
                        </LemonButton>
                    </div>
                )}

                {/* {isInitialLoad ? (
                    <div className="p-4">
                        <Skeleton active />
                    </div>
                ) : (
                    <>
                        {people && (
                            <>
                                {!!people.crossDataset?.length && people.seriesId !== undefined && (
                                    <LemonSelect
                                        fullWidth
                                        className="mb-2"
                                        value={String(people.seriesId)}
                                        onChange={(_id) =>
                                            typeof _id === 'string' ? switchToDataPoint(parseInt(_id, 10)) : null
                                        }
                                        options={people.crossDataset.map((dataPoint) => ({
                                            value: `${dataPoint.id}`,
                                            label: (
                                                <InsightLabel
                                                    seriesColor={getSeriesColor(dataPoint.id)}
                                                    action={dataPoint.action}
                                                    breakdownValue={
                                                        dataPoint.breakdown_value === ''
                                                            ? 'None'
                                                            : dataPoint.breakdown_value?.toString()
                                                    }
                                                    showCountedByTag={showCountedByTag}
                                                    hasMultipleSeries={hasMultipleSeries}
                                                />
                                            ),
                                        }))}
                                    />
                                )}
                            </>
                        )}
                    </>
                )} */}
            </LemonModal>
        </>
    )
}

export type OpenPersonsModalProps = Omit<PersonsModalProps, 'onClose' | 'onAfterClose'>

export const openPersonsModal = (props: OpenPersonsModalProps): void => {
    const featureFlags = featureFlagLogic.findMounted()?.values?.featureFlags

    if (!featureFlags || !featureFlags[FEATURE_FLAGS.PERSONS_MODAL_V2]) {
        // Currrently this will display 2 modals, as we want to test this comparison in production
        return
    }

    const div = document.createElement('div')
    function destroy(): void {
        const unmountResult = ReactDOM.unmountComponentAtNode(div)
        if (unmountResult && div.parentNode) {
            div.parentNode.removeChild(div)
        }
    }

    document.body.appendChild(div)
    ReactDOM.render(<PersonsModalV2 {...props} onAfterClose={destroy} />, div)
}

interface ActorRowProps {
    actor: ActorType
}

export function ActorRow({ actor }: ActorRowProps): JSX.Element {
    if (isGroupType(actor)) {
        return (
            <div key={actor.id} className="person-row">
                <div className="person-ids">
                    <strong>
                        <GroupActorHeader actor={actor} />
                    </strong>
                </div>
            </div>
        )
    } else {
        return (
            <div key={actor.id} className="person-ids">
                <strong>
                    <PersonHeader person={actor} withIcon={false} />
                </strong>
                <CopyToClipboardInline
                    explicitValue={actor.distinct_ids[0]}
                    iconStyle={{ color: 'var(--primary)' }}
                    iconPosition="end"
                    className="text-xs text-muted-alt"
                >
                    {midEllipsis(actor.distinct_ids[0], 32)}
                </CopyToClipboardInline>
            </div>
        )
    }
}
