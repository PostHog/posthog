import './PersonsModal.scss'

import { LemonBadge, LemonButton, LemonDivider, LemonInput, LemonModal, LemonSelect, Link } from '@posthog/lemon-ui'
import { LemonModalProps } from '@posthog/lemon-ui'
import { Skeleton } from 'antd'
import { useActions, useValues } from 'kea'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { triggerExport } from 'lib/components/ExportButton/exporter'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { PropertiesTimeline } from 'lib/components/PropertiesTimeline'
import { IconPlayCircle, IconUnfoldLess, IconUnfoldMore } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { capitalizeFirstLetter, isGroupType, midEllipsis, pluralize } from 'lib/utils'
import { useCallback, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { isOtherBreakdown } from 'scenes/insights/utils'
import { GroupActorDisplay, groupDisplayId } from 'scenes/persons/GroupActorDisplay'
import { asDisplay } from 'scenes/persons/person-utils'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { SessionPlayerModal } from 'scenes/session-recordings/player/modal/SessionPlayerModal'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { teamLogic } from 'scenes/teamLogic'

import { Noun } from '~/models/groupsModel'
import { InsightActorsQuery } from '~/queries/schema'
import {
    ActorType,
    ExporterFormat,
    PropertiesTimelineFilterType,
    PropertyDefinitionType,
    SessionRecordingType,
} from '~/types'

import { personsModalLogic } from './personsModalLogic'
import { SaveCohortModal } from './SaveCohortModal'

export interface PersonsModalProps extends Pick<LemonModalProps, 'inline'> {
    onAfterClose?: () => void
    query?: InsightActorsQuery | null
    url?: string | null
    urlsIndex?: number
    urls?: {
        label: string | JSX.Element
        value: string
    }[]
    title: React.ReactNode | ((actorLabel: string) => React.ReactNode)
}

export function PersonsModal({
    url: _url,
    urlsIndex,
    urls,
    query: _query,
    title,
    onAfterClose,
    inline,
}: PersonsModalProps): JSX.Element {
    const [selectedUrlIndex, setSelectedUrlIndex] = useState(urlsIndex || 0)
    const originalUrl = (urls || [])[selectedUrlIndex]?.value || _url || ''

    const logic = personsModalLogic({
        url: originalUrl,
        query: _query,
    })

    const {
        query: query,
        actors,
        actorsResponseLoading,
        actorsResponse,
        insightActorsQueryOptions,
        searchTerm,
        actorLabel,
        isCohortModalOpen,
        isModalOpen,
        missingActorsCount,
        propertiesTimelineFilterFromUrl,
        exploreUrl,
        ActorsQuery,
    } = useValues(logic)
    const { updateActorsQuery, setSearchTerm, saveAsCohort, setIsCohortModalOpen, closeModal, loadNextActors } =
        useActions(logic)
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic)
    const { currentTeam } = useValues(teamLogic)
    const totalActorsCount = missingActorsCount + actors.length

    const getTitle = useCallback(() => {
        if (typeof title === 'function') {
            return title(capitalizeFirstLetter(actorLabel.plural))
        }

        if (isOtherBreakdown(title)) {
            return 'Other'
        }

        return title
    }, [title, actorLabel.plural])

    return (
        <>
            <LemonModal
                title={null}
                isOpen={isModalOpen}
                onClose={closeModal}
                onAfterClose={onAfterClose}
                simple
                width={560}
                inline={inline}
            >
                <LemonModal.Header>
                    <h3>{getTitle()}</h3>
                </LemonModal.Header>
                <div className="px-6 py-2">
                    {actorsResponse && !!missingActorsCount && (
                        <MissingPersonsAlert actorLabel={actorLabel} missingActorsCount={missingActorsCount} />
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
                            onChange={(v) => {
                                if (v !== null && v >= 0) {
                                    setSelectedUrlIndex(v)
                                }
                            }}
                            options={(urls || []).map((url, index) => ({
                                value: index,
                                label: url.label,
                            }))}
                        />
                    ) : null}

                    {query &&
                        Object.entries(insightActorsQueryOptions ?? {})
                            .filter(([, value]) => !!value)
                            .map(([key, options]) => (
                                <div key={key}>
                                    <LemonSelect
                                        fullWidth
                                        className="mb-2"
                                        value={query?.[key] ?? null}
                                        onChange={(v) => updateActorsQuery({ [key]: v })}
                                        options={options}
                                    />
                                </div>
                            ))}

                    <div className="flex items-center gap-2 text-muted">
                        {actorsResponseLoading ? (
                            <>
                                <Spinner />
                                <span>Loading {actorLabel.plural}...</span>
                            </>
                        ) : (
                            <span>
                                {actorsResponse?.next || actorsResponse?.next_offset ? 'More than ' : ''}
                                <b>
                                    {totalActorsCount || 'No'} unique{' '}
                                    {pluralize(totalActorsCount, actorLabel.singular, actorLabel.plural, false)}
                                </b>
                            </span>
                        )}
                    </div>
                </div>
                <div className="px-6 overflow-hidden flex flex-col">
                    <div className="relative min-h-20 p-2 space-y-2 rounded bg-border-light overflow-y-auto mb-2">
                        {actors && actors.length > 0 ? (
                            <>
                                {actors.map((actor) => (
                                    <ActorRow
                                        key={actor.id}
                                        actor={actor}
                                        onOpenRecording={(sessionRecording) => {
                                            openSessionPlayer(sessionRecording)
                                        }}
                                        propertiesTimelineFilter={
                                            actor.type == 'person' && currentTeam?.person_on_events_querying_enabled
                                                ? propertiesTimelineFilterFromUrl
                                                : undefined
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

                        {(actorsResponse?.next || actorsResponse?.next_offset) && (
                            <div className="m-4 flex justify-center">
                                <LemonButton type="primary" onClick={loadNextActors} loading={actorsResponseLoading}>
                                    Load more {actorLabel.plural}
                                </LemonButton>
                            </div>
                        )}
                    </div>
                </div>
                <LemonModal.Footer>
                    <div className="flex justify-between gap-2 w-full">
                        <div className="flex gap-2">
                            <LemonButton
                                type="secondary"
                                onClick={() => {
                                    void triggerExport({
                                        export_format: ExporterFormat.CSV,
                                        export_context: query
                                            ? { source: ActorsQuery as Record<string, any> }
                                            : { path: originalUrl },
                                    })
                                }}
                                data-attr="person-modal-download-csv"
                                disabled={!actors.length}
                            >
                                Download CSV
                            </LemonButton>
                            {actors && actors.length > 0 && !isGroupType(actors[0]) && (
                                <LemonButton
                                    onClick={() => setIsCohortModalOpen(true)}
                                    type="secondary"
                                    data-attr="person-modal-save-as-cohort"
                                    disabled={!actors.length}
                                >
                                    Save as cohort
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
                </LemonModal.Footer>
            </LemonModal>
            <SaveCohortModal
                onSave={(title) => saveAsCohort(title)}
                onCancel={() => setIsCohortModalOpen(false)}
                isOpen={isCohortModalOpen}
            />
            <SessionPlayerModal />
        </>
    )
}

interface ActorRowProps {
    actor: ActorType
    onOpenRecording: (sessionRecording: Pick<SessionRecordingType, 'id' | 'matching_events'>) => void
    propertiesTimelineFilter?: PropertiesTimelineFilterType
}

export function ActorRow({ actor, onOpenRecording, propertiesTimelineFilter }: ActorRowProps): JSX.Element {
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
            actor.matched_recordings[0].session_id &&
                onOpenRecording({
                    id: actor.matched_recordings[0].session_id,
                    matching_events: actor.matched_recordings,
                })
        }
    }

    const matchedRecordings = actor.matched_recordings || []

    return (
        <div className="relative border rounded bg-bg-light">
            <div className="flex items-center gap-2 p-2">
                <LemonButton
                    noPadding
                    active={expanded}
                    onClick={() => setExpanded(!expanded)}
                    icon={expanded ? <IconUnfoldLess /> : <IconUnfoldMore />}
                    title={expanded ? 'Show less' : 'Show more'}
                    data-attr={`persons-modal-expand-${actor.id}`}
                />

                <ProfilePicture name={name} size="md" />

                <div className="flex-1 overflow-hidden">
                    {isGroupType(actor) ? (
                        <div className="font-bold">
                            <GroupActorDisplay actor={actor} />
                        </div>
                    ) : (
                        <>
                            <div className="font-bold flex items-start">
                                <PersonDisplay person={actor} withIcon={false} />
                            </div>
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
                            sideIcon={matchedRecordings.length === 1 ? <IconPlayCircle /> : null}
                            type="secondary"
                            size="small"
                        >
                            {matchedRecordings.length > 1 ? `${matchedRecordings.length} recordings` : 'View recording'}
                        </LemonButton>
                    </div>
                ) : null}
            </div>

            {expanded ? (
                <div className="PersonsModal__tabs bg-side border-t rounded-b">
                    <LemonTabs
                        activeKey={tab}
                        onChange={setTab}
                        tabs={[
                            {
                                key: 'properties',
                                label: 'Properties',
                                content: propertiesTimelineFilter ? (
                                    <PropertiesTimeline actor={actor} filter={propertiesTimelineFilter} />
                                ) : (
                                    <PropertiesTable
                                        type={actor.type /* "person" or "group" */ as PropertyDefinitionType}
                                        properties={actor.properties}
                                    />
                                ),
                            },
                            {
                                key: 'recordings',
                                label: 'Recordings',
                                content: (
                                    <div className="p-2 space-y-2 font-medium mt-1">
                                        <div className="flex justify-between items-center px-2">
                                            <span>{pluralize(matchedRecordings.length, 'matched recording')}</span>
                                        </div>
                                        <ul className="space-y-px">
                                            {matchedRecordings?.length
                                                ? matchedRecordings.map((recording, i) => (
                                                      <>
                                                          <LemonDivider className="my-0" />
                                                          <li key={i}>
                                                              <LemonButton
                                                                  key={i}
                                                                  fullWidth
                                                                  onClick={() => {
                                                                      recording.session_id &&
                                                                          onOpenRecording({
                                                                              id: recording.session_id,
                                                                              matching_events: [
                                                                                  {
                                                                                      events: recording.events,
                                                                                      session_id: recording.session_id,
                                                                                  },
                                                                              ],
                                                                          })
                                                                  }}
                                                              >
                                                                  <div className="flex flex-1 justify-between gap-2 items-center">
                                                                      <span>View recording {i + 1}</span>
                                                                      <IconPlayCircle className="text-xl text-muted" />
                                                                  </div>
                                                              </LemonButton>
                                                          </li>
                                                      </>
                                                  ))
                                                : null}
                                        </ul>
                                    </div>
                                ),
                            },
                        ]}
                    />
                </div>
            ) : null}

            {actor.value_at_data_point !== null && (
                <Tooltip title={`${name}'s value for this data point.`}>
                    <LemonBadge.Number
                        count={actor.value_at_data_point}
                        maxDigits={Infinity}
                        position="top-right"
                        style={{ pointerEvents: 'auto' }}
                    />
                </Tooltip>
            )}
        </div>
    )
}

export function MissingPersonsAlert({
    actorLabel,
    missingActorsCount,
}: {
    actorLabel: Noun
    missingActorsCount: number
}): JSX.Element {
    return (
        <LemonBanner type="info" className="mb-2">
            {missingActorsCount} {missingActorsCount > 1 ? `${actorLabel.plural} are` : `${actorLabel.singular} is`} not
            shown because they've been merged with those listed, or deleted.{' '}
            <Link to="https://posthog.com/docs/how-posthog-works/queries#insights-counting-unique-persons">
                Learn more.
            </Link>
        </LemonBanner>
    )
}

export type OpenPersonsModalProps = Omit<PersonsModalProps, 'onClose' | 'onAfterClose'>

export const openPersonsModal = (props: OpenPersonsModalProps): void => {
    const div = document.createElement('div')
    const root = createRoot(div)
    function destroy(): void {
        root.unmount()
        if (div.parentNode) {
            div.parentNode.removeChild(div)
        }
    }

    document.body.appendChild(div)
    root.render(<PersonsModal {...props} onAfterClose={destroy} />)
}
