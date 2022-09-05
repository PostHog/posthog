import React, { useState } from 'react'
import { useActions, useValues } from 'kea'
import { DownloadOutlined } from '@ant-design/icons'
import { ActorType, ExporterFormat } from '~/types'
import { personsModalLogic } from './personsModalLogic'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { capitalizeFirstLetter, isGroupType, midEllipsis, pluralize } from 'lib/utils'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { GroupActorHeader, groupDisplayId } from 'scenes/persons/GroupActorHeader'
import { IconArrowDropDown, IconPlay, IconSave, IconUnfoldLess, IconUnfoldMore } from 'lib/components/icons'
import { triggerExport } from 'lib/components/ExportButton/exporter'
import { LemonButton, LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'
import { asDisplay, PersonHeader } from 'scenes/persons/PersonHeader'
import ReactDOM from 'react-dom'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { SaveCohortModal } from './SaveCohortModal'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { Skeleton, Tabs } from 'antd'
import { SessionPlayerDrawer } from 'scenes/session-recordings/SessionPlayerDrawer'
import { sessionPlayerDrawerLogic } from 'scenes/session-recordings/sessionPlayerDrawerLogic'
import { RecordingWatchedSource } from 'lib/utils/eventUsageLogic'
import { AlertMessage } from 'lib/components/AlertMessage'

export interface PersonsModalProps {
    onAfterClose?: () => void
    url?: string
    urlsIndex?: number
    urls?: {
        label: string | JSX.Element
        value: string
    }[]
    title: React.ReactNode | ((actorLabel: string) => React.ReactNode)
}

function PersonsModal({ url: _url, urlsIndex, urls, title, onAfterClose }: PersonsModalProps): JSX.Element {
    const [selectedUrlIndex, setSelectedUrlIndex] = useState(urlsIndex || 0)
    const originalUrl = (urls || [])[selectedUrlIndex]?.value || _url || ''

    const logic = personsModalLogic({
        url: originalUrl,
    })

    const {
        actors,
        actorsResponseLoading,
        actorsResponse,
        searchTerm,
        actorType,
        actorLabel,
        isCohortModalOpen,
        isModalOpen,
    } = useValues(logic)
    const { loadActors, setSearchTerm, saveCohortWithUrl, setIsCohortModalOpen, closeModal } = useActions(logic)
    const { openSessionPlayer, closeSessionPlayer } = useActions(sessionPlayerDrawerLogic)

    return (
        <>
            <LemonModal
                title={''}
                isOpen={isModalOpen}
                onClose={closeModal}
                onAfterClose={onAfterClose}
                simple
                width={600}
            >
                <LemonModal.Header>
                    <h3>{typeof title === 'function' ? title(capitalizeFirstLetter(actorLabel.plural)) : title}</h3>
                </LemonModal.Header>
                <div className="px-6 py-2">
                    {actorsResponse && !!actorsResponse.missing_persons && (
                        <AlertMessage type="info" className="mb-2">
                            {actorsResponse.missing_persons}{' '}
                            {actorsResponse.missing_persons > 1
                                ? `${actorLabel.plural} are`
                                : `${actorLabel.singular} is`}{' '}
                            not shown because they've been lost.{' '}
                            <a href="https://posthog.com/docs/how-posthog-works/queries#insights-counting-unique-persons">
                                Read more here for when this can happen
                            </a>
                            .
                        </AlertMessage>
                    )}
                    <LemonInput
                        type="search"
                        placeholder="Search for persons by email, name, or ID"
                        fullWidth
                        value={searchTerm}
                        onChange={setSearchTerm}
                        className="my-2"
                    />

                    {urls ? (
                        <LemonSelect
                            fullWidth
                            className="mb-2"
                            value={selectedUrlIndex}
                            onChange={(v) => v && setSelectedUrlIndex(v)}
                            options={(urls || []).map((url, index) => ({
                                value: index,
                                label: url.label,
                            }))}
                        />
                    ) : null}

                    <div className="flex items-center gap-2 text-muted">
                        {actorsResponseLoading ? (
                            <>
                                <Spinner />
                                <span>Loading {actorLabel.plural}...</span>
                            </>
                        ) : (
                            <span>
                                {actorsResponse?.next ? 'More than ' : ''}
                                <b>
                                    {actorsResponse?.total_count} unique{' '}
                                    {actorsResponse?.total_count === 1 ? actorLabel.singular : actorLabel.plural}
                                </b>
                            </span>
                        )}
                    </div>
                </div>
                <div className="px-6 overflow-hidden flex flex-col">
                    <div className="relative min-h-20 p-2 space-y-2 rounded bg-border-light overflow-y-auto mb-2">
                        {actors && actors.length > 0 ? (
                            <>
                                {actors.map((x) => (
                                    <ActorRow
                                        key={x.id}
                                        actor={x}
                                        onOpenRecording={(id) =>
                                            openSessionPlayer(id, RecordingWatchedSource.PersonModal)
                                        }
                                    />
                                ))}
                            </>
                        ) : actorsResponseLoading ? (
                            <Skeleton title={false} />
                        ) : (
                            <div className="text-center p-5">
                                We couldn't find any matching {actorLabel.plural} for this data point.
                            </div>
                        )}

                        {actorsResponse?.next && (
                            <div className="m-4 flex justify-center">
                                <LemonButton
                                    type="primary"
                                    onClick={() => actorsResponse?.next && loadActors({ url: actorsResponse?.next })}
                                    loading={actorsResponseLoading}
                                >
                                    Load more {actorLabel.plural}
                                </LemonButton>
                            </div>
                        )}
                    </div>
                </div>
                <LemonModal.Footer>
                    {actorType === 'person' ? (
                        <LemonButton
                            onClick={() => setIsCohortModalOpen(true)}
                            icon={<IconSave />}
                            type="secondary"
                            data-attr="person-modal-save-as-cohort"
                            disabled={actorsResponse?.total_count === 0}
                        >
                            Save as cohort
                        </LemonButton>
                    ) : null}
                    <LemonButton
                        icon={<DownloadOutlined />}
                        type="secondary"
                        onClick={() => {
                            triggerExport({
                                export_format: ExporterFormat.CSV,
                                export_context: {
                                    path: originalUrl,
                                },
                            })
                        }}
                        data-attr="person-modal-download-csv"
                        disabled={actorsResponse?.total_count === 0}
                    >
                        Download CSV
                    </LemonButton>
                </LemonModal.Footer>
            </LemonModal>
            <SaveCohortModal
                onSave={(title) => saveCohortWithUrl(title)}
                onCancel={() => setIsCohortModalOpen(false)}
                isOpen={isCohortModalOpen}
            />
            <SessionPlayerDrawer onClose={() => closeSessionPlayer()} />
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
        <div className="border rounded overflow-hidden bg-white">
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
                                    <div className="text-center m-2">No recordings</div>
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
    const div = document.createElement('div')
    function destroy(): void {
        const unmountResult = ReactDOM.unmountComponentAtNode(div)
        if (unmountResult && div.parentNode) {
            div.parentNode.removeChild(div)
        }
    }

    document.body.appendChild(div)
    ReactDOM.render(<PersonsModal {...props} onAfterClose={destroy} />, div)
}
