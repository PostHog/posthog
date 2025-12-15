import './PersonsModal.scss'

import { useActions, useValues } from 'kea'
import React, { useCallback, useState } from 'react'
import { createRoot } from 'react-dom/client'

import { IconCollapse, IconExpand } from '@posthog/icons'
import {
    LemonBadge,
    LemonBanner,
    LemonButton,
    LemonDivider,
    LemonInput,
    LemonModal,
    LemonModalProps,
    LemonSelect,
    LemonSkeleton,
    Link,
} from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { PropertiesTimeline } from 'lib/components/PropertiesTimeline'
import ViewRecordingButton from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { capitalizeFirstLetter, isGroupType, midEllipsis, pluralize } from 'lib/utils'
import { InsightErrorState, InsightValidationError } from 'scenes/insights/EmptyStates'
import { isOtherBreakdown } from 'scenes/insights/utils'
import { GroupActorDisplay, groupDisplayId } from 'scenes/persons/GroupActorDisplay'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { asDisplay } from 'scenes/persons/person-utils'
import { teamLogic } from 'scenes/teamLogic'

import { Noun } from '~/models/groupsModel'
import { MAX_SELECT_RETURNED_ROWS } from '~/queries/nodes/DataTable/DataTableExport'
import { ActorType, ExporterFormat, PropertiesTimelineFilterType, PropertyDefinitionType } from '~/types'

import { SaveCohortModal } from './SaveCohortModal'
import { cleanedInsightActorsQueryOptions } from './persons-modal-utils'
import { PersonModalLogicProps, personsModalLogic } from './personsModalLogic'

export interface PersonsModalProps extends PersonModalLogicProps, Pick<LemonModalProps, 'inline'> {
    onAfterClose?: () => void
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
    additionalSelect,
    orderBy,
}: PersonsModalProps): JSX.Element {
    const [selectedUrlIndex, setSelectedUrlIndex] = useState(urlsIndex || 0)
    const originalUrl = (urls || [])[selectedUrlIndex]?.value || _url || ''

    const logic = personsModalLogic({
        url: originalUrl,
        query: _query,
        additionalSelect,
        orderBy,
    })

    const {
        query,
        actors,
        actorsResponseLoading,
        actorsResponse,
        errorObject,
        validationError,
        insightActorsQueryOptions,
        searchTerm,
        actorLabel,
        isCohortModalOpen,
        isModalOpen,
        missingActorsCount,
        propertiesTimelineFilterFromUrl,
        insightEventsQueryUrl,
        exploreUrl,
        actorsQuery,
    } = useValues(logic)
    const { updateActorsQuery, setSearchTerm, saveAsCohort, setIsCohortModalOpen, closeModal, loadNextActors } =
        useActions(logic)
    const { currentTeam } = useValues(teamLogic)
    const { startExport } = useActions(exportsLogic)

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

    const hasGroups = actors.some((actor) => isGroupType(actor))

    return (
        <>
            <LemonModal
                data-attr="persons-modal"
                title={null}
                isOpen={isModalOpen}
                onClose={closeModal}
                onAfterClose={onAfterClose}
                simple
                width={600}
                inline={inline}
            >
                <LemonModal.Header>
                    <h3>{getTitle()}</h3>
                </LemonModal.Header>
                <div className="px-4 py-2">
                    {actorsResponse && !!missingActorsCount && !hasGroups && (
                        <MissingPersonsAlert actorLabel={actorLabel} missingActorsCount={missingActorsCount} />
                    )}
                    <LemonInput
                        type="search"
                        placeholder={
                            hasGroups ? 'Search for groups by name or ID' : 'Search for persons by email, name, or ID'
                        }
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
                        cleanedInsightActorsQueryOptions(insightActorsQueryOptions, query).map(([key, options]) =>
                            key === 'breakdowns'
                                ? options.map(({ values }, index) => (
                                      <div key={`${key}_${index}`}>
                                          <LemonSelect
                                              fullWidth
                                              className="mb-2"
                                              value={query?.breakdown?.[index] ?? null}
                                              onChange={(v) => {
                                                  const breakdown = Array.isArray(query.breakdown)
                                                      ? [...query.breakdown]
                                                      : []
                                                  breakdown[index] = v
                                                  updateActorsQuery({ breakdown })
                                              }}
                                              options={values}
                                          />
                                      </div>
                                  ))
                                : options.length > 1 && (
                                      <div key={key}>
                                          <LemonSelect
                                              fullWidth
                                              className="mb-2"
                                              value={query?.[key] ?? null}
                                              onChange={(v) => updateActorsQuery({ [key]: v })}
                                              options={options}
                                          />
                                      </div>
                                  )
                        )}

                    <div className="flex items-center gap-2 text-secondary">
                        {actorsResponseLoading ? (
                            <>
                                <Spinner />
                                <span>Loading {actorLabel.plural}...</span>
                            </>
                        ) : (
                            <span>
                                {actorsResponse?.next || actorsResponse?.offset ? 'More than ' : ''}
                                <b>
                                    {totalActorsCount || 'No'} unique{' '}
                                    {pluralize(totalActorsCount, actorLabel.singular, actorLabel.plural, false)}
                                </b>
                            </span>
                        )}
                    </div>
                </div>
                <div className="px-4 overflow-hidden flex flex-col">
                    <div className="relative min-h-20 p-2 deprecated-space-y-2 rounded bg-border-light overflow-y-auto mb-2">
                        {errorObject ? (
                            validationError ? (
                                <InsightValidationError query={query} detail={validationError} />
                            ) : (
                                <InsightErrorState query={query} />
                            )
                        ) : actors && actors.length > 0 ? (
                            <>
                                {actors.map((actor) => (
                                    <ActorRow
                                        key={actor.id}
                                        actor={actor}
                                        propertiesTimelineFilter={
                                            actor.type == 'person' && currentTeam?.person_on_events_querying_enabled
                                                ? propertiesTimelineFilterFromUrl
                                                : undefined
                                        }
                                    />
                                ))}
                            </>
                        ) : actorsResponseLoading ? (
                            <div className="deprecated-space-y-3">
                                <LemonSkeleton active={false} className="h-4 w-full" />
                                <LemonSkeleton active={false} className="h-4 w-3/5" />
                            </div>
                        ) : (
                            <div className="text-center p-5" data-attr="persons-modal-no-matches">
                                We couldn't find any matching {actorLabel.plural} for this data point.
                            </div>
                        )}

                        {(actorsResponse?.next || actorsResponse?.offset) && (
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
                            {actors.length > 0 && (
                                <LemonButton
                                    type="secondary"
                                    onClick={() => {
                                        startExport({
                                            export_format: ExporterFormat.CSV,
                                            export_context: query
                                                ? {
                                                      source: {
                                                          ...actorsQuery,
                                                          select: actorsQuery!.select?.filter(
                                                              (c) => c !== 'matched_recordings'
                                                          ),
                                                          source: { ...actorsQuery!.source, includeRecordings: false },
                                                      },
                                                  }
                                                : { path: originalUrl },
                                        })
                                    }}
                                    tooltip={`Up to ${MAX_SELECT_RETURNED_ROWS} persons will be exported`}
                                    data-attr="person-modal-download-csv"
                                >
                                    Download CSV
                                </LemonButton>
                            )}
                            {actors.length > 0 && !isGroupType(actors[0]) && (
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
                </LemonModal.Footer>
            </LemonModal>
            <SaveCohortModal
                onSave={(title) => saveAsCohort(title)}
                onCancel={() => setIsCohortModalOpen(false)}
                isOpen={isCohortModalOpen}
            />
        </>
    )
}

interface ActorRowProps {
    actor: ActorType
    propertiesTimelineFilter?: PropertiesTimelineFilterType
}

export function ActorRow({ actor, propertiesTimelineFilter }: ActorRowProps): JSX.Element {
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
        }
    }

    const matchedRecordings = actor.matched_recordings || []

    return (
        <div className="relative border rounded bg-surface-primary">
            <div className="flex items-center gap-2 p-2">
                <LemonButton
                    noPadding
                    active={expanded}
                    onClick={() => setExpanded(!expanded)}
                    icon={expanded ? <IconCollapse /> : <IconExpand />}
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
                            {actor.distinct_ids?.[0] && (
                                <CopyToClipboardInline
                                    explicitValue={actor.distinct_ids[0]}
                                    iconStyle={{ color: 'var(--color-accent)' }}
                                    iconPosition="end"
                                    className="text-xs text-secondary"
                                >
                                    {midEllipsis(actor.distinct_ids[0], 32)}
                                </CopyToClipboardInline>
                            )}
                        </>
                    )}
                </div>

                {matchedRecordings.length > 1 ? (
                    <div className="shrink-0">
                        <LemonButton
                            onClick={onOpenRecordingClick}
                            sideIcon={matchedRecordings.length === 1 ? <IconPlayCircle /> : null}
                            type="secondary"
                            status={matchedRecordings.length > 1 ? 'alt' : undefined}
                            size="small"
                        >
                            {matchedRecordings.length} recordings
                        </LemonButton>
                    </div>
                ) : matchedRecordings.length === 1 ? (
                    <ViewRecordingButton
                        sessionId={matchedRecordings[0].session_id}
                        checkIfViewed={true}
                        matchingEvents={[
                            {
                                events: matchedRecordings[0].events,
                                session_id: matchedRecordings[0].session_id,
                            },
                        ]}
                        type="secondary"
                        inModal={true}
                    />
                ) : null}
            </div>

            {expanded ? (
                <div className="PersonsModal__tabs bg-primary border-t rounded-b">
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
                                    <div className="p-2 deprecated-space-y-2 font-medium mt-1">
                                        <div className="flex justify-between items-center px-2">
                                            <span>{pluralize(matchedRecordings.length, 'matched recording')}</span>
                                        </div>
                                        <ul className="deprecated-space-y-px">
                                            {matchedRecordings?.length
                                                ? matchedRecordings.map((recording, i) => (
                                                      <React.Fragment key={i}>
                                                          <LemonDivider className="my-0" />
                                                          <li>
                                                              <ViewRecordingButton
                                                                  sessionId={recording.session_id}
                                                                  matchingEvents={[
                                                                      {
                                                                          events: recording.events,
                                                                          session_id: recording.session_id,
                                                                      },
                                                                  ]}
                                                                  label={`View recording ${i + 1}`}
                                                                  checkIfViewed={true}
                                                                  inModal={true}
                                                                  fullWidth={true}
                                                              />
                                                          </li>
                                                      </React.Fragment>
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
            {missingActorsCount}{' '}
            <span>{missingActorsCount > 1 ? `${actorLabel.plural} are` : `${actorLabel.singular} is`}</span> not shown
            because they've been merged with those listed, or deleted.{' '}
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
