import React, { useState } from 'react'
import { useActions, useValues } from 'kea'
import { DownloadOutlined } from '@ant-design/icons'
import { ActorType, ExporterFormat } from '~/types'
import { personsModalLogic } from './personsModalV2Logic'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { isGroupType, midEllipsis, pluralize } from 'lib/utils'
import './PersonsModal.scss'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { GroupActorHeader, groupDisplayId } from 'scenes/persons/GroupActorHeader'
import {
    IconArrowDropDown,
    IconPersonFilled,
    IconPlay,
    IconSave,
    IconUnfoldLess,
    IconUnfoldMore,
} from 'lib/components/icons'
import { triggerExport } from 'lib/components/ExportButton/exporter'
import { LemonButton, LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'
import { asDisplay, PersonHeader } from 'scenes/persons/PersonHeader'
import ReactDOM from 'react-dom'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SaveCohortModal } from './SaveCohortModal'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { Tabs } from 'antd'
import { SessionPlayerDrawer } from 'scenes/session-recordings/SessionPlayerDrawer'

export interface PersonsModalProps {
    onAfterClose?: () => void
    url: string
    urls: {
        label: string | JSX.Element
        value: string
    }[]
    title: React.ReactNode
    actorType: ActorType['type']
}

function PersonsModalV2({ url, urls, title, onAfterClose }: PersonsModalProps): JSX.Element {
    const [chosenUrl, setChosenUrl] = useState(url)
    const [isOpen, setIsOpen] = useState(true)
    const [cohortModalOpen, setCohortModalOpen] = useState(false)
    const [sessionId, setSessionId] = useState<string | undefined>(undefined)
    const logic = personsModalLogic({
        url: chosenUrl,
        closeModal: () => {
            setIsOpen(false)
            setCohortModalOpen(false)
        },
    })

    const { allPeople, peopleLoading, people: peopleRes, searchTerm } = useValues(logic)
    const { loadPeople, setSearchTerm, saveCohortWithUrl } = useActions(logic)

    // const showCountedByTag = !!people?.crossDataset?.find(({ action }) => action?.math && action.math !== 'total')
    // const hasMultipleSeries = !!people?.crossDataset?.find(({ action }) => action?.order)

    // TODO: Maybe move this to the logic...
    const onOpenRecording = (id: string): void => {
        setSessionId(id)
        window.location.hash = '#sessionRecordingId=' + id
    }

    const onCloseRecording = (): void => {
        setSessionId(undefined)
        window.location.hash = ''
    }

    return (
        <>
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

                        <LemonSelect
                            fullWidth
                            className="mb-2"
                            value={chosenUrl}
                            onChange={(v) => v && setChosenUrl(v)}
                            options={(urls || []).map((url) => ({
                                value: url.value,
                                label: url.label,
                            }))}
                        />

                        <div className="flex items-center gap-2 text-muted">
                            {peopleLoading ? (
                                <>
                                    <Spinner />
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
                                onClick={() => setCohortModalOpen(true)}
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
                <div className="relative min-h-20 space-y-2">
                    {allPeople && allPeople.length > 0 ? (
                        <>
                            {allPeople.map((x) => (
                                <ActorRow key={x.id} actor={x} onOpenRecording={onOpenRecording} />
                            ))}
                        </>
                    ) : peopleRes ? (
                        <div className="text-center">We couldn't find any matching results for this data point.</div>
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
            <SaveCohortModal
                onSave={(title) => saveCohortWithUrl(title)}
                onCancel={() => setCohortModalOpen(false)}
                isOpen={cohortModalOpen}
            />
            {sessionId && <SessionPlayerDrawer onClose={() => onCloseRecording()} />}
        </>
    )
}

interface ActorRowProps {
    actor: ActorType
    onOpenRecording: (id: string) => void
}

export function ActorRow({ actor, onOpenRecording }: ActorRowProps): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const [tab, setTab] = useState('properties')
    const name = isGroupType(actor) ? groupDisplayId(actor.group_key, actor.properties) : asDisplay(actor)

    const onOpenRecordingClick = (): void => {
        if (!actor.matched_recordings) {
            return
        }
        if (actor.matched_recordings?.length > 1) {
            setExpanded(true)
            setTab('recordings')
        } else {
            onOpenRecording(actor.matched_recordings[0].session_id)
        }
    }

    const matchedRecordings = actor.matched_recordings || []

    return (
        <div className="border rounded overflow-hidden">
            <div className="flex items-center gap-2 p-2">
                <LemonButton
                    noPadding
                    status="stealth"
                    active={expanded}
                    onClick={() => setExpanded(!expanded)}
                    icon={expanded ? <IconUnfoldLess /> : <IconUnfoldMore />}
                    title={expanded ? 'Show less' : 'Show more'}
                />

                <ProfilePicture name={name} size="md" />

                <div className="flex-1 overflow-hidden">
                    {isGroupType(actor) ? (
                        <strong>
                            <GroupActorHeader actor={actor} />
                        </strong>
                    ) : (
                        <>
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
                        </>
                    )}
                </div>

                {matchedRecordings.length && matchedRecordings.length > 0 ? (
                    <div className="shrink-0">
                        <LemonButton
                            onClick={onOpenRecordingClick}
                            sideIcon={matchedRecordings.length > 1 ? <IconArrowDropDown /> : null}
                            type="secondary"
                            size="small"
                        >
                            View {pluralize(matchedRecordings.length, 'recording', undefined, false)}
                        </LemonButton>
                    </div>
                ) : null}
            </div>

            {expanded ? (
                <div className="bg-side border-t">
                    <Tabs defaultActiveKey={tab} onChange={setTab} tabBarStyle={{ paddingLeft: 20, marginBottom: 0 }}>
                        <Tabs.TabPane tab="Properties" key="properties">
                            {Object.keys(actor.properties).length ? (
                                <PropertiesTable properties={actor.properties} />
                            ) : (
                                <p>There are no properties.</p>
                            )}
                        </Tabs.TabPane>
                        <Tabs.TabPane tab="Recordings" key="recordings">
                            <div className="p-2 space-y-2">
                                {matchedRecordings?.length ? (
                                    matchedRecordings.map((recording, i) => (
                                        <LemonButton
                                            key={recording.session_id}
                                            onClick={() => onOpenRecording(recording.session_id)}
                                            icon={<IconPlay />}
                                            type="secondary"
                                        >
                                            View recording {i + 1}
                                        </LemonButton>
                                    ))
                                ) : (
                                    <p>No recordings</p>
                                )}
                            </div>
                        </Tabs.TabPane>
                    </Tabs>
                </div>
            ) : null}
        </div>
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
