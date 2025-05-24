import './PersonsModal.scss'

import { IconCollapse, IconExpand, IconAIText, IconChevronDown, IconInfo, IconTarget } from '@posthog/icons'
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
    LemonTable,
    LemonTag,
    LemonTabs,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { PropertiesTimeline } from 'lib/components/PropertiesTimeline'
import ViewRecordingButton from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { capitalizeFirstLetter, isGroupType, midEllipsis, pluralize } from 'lib/utils'
import React, { useCallback, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { InsightErrorState, InsightValidationError } from 'scenes/insights/EmptyStates'
import { isOtherBreakdown } from 'scenes/insights/utils'
import { GroupActorDisplay, groupDisplayId } from 'scenes/persons/GroupActorDisplay'
import { asDisplay } from 'scenes/persons/person-utils'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { teamLogic } from 'scenes/teamLogic'

import { Noun } from '~/models/groupsModel'
import { MAX_SELECT_RETURNED_ROWS } from '~/queries/nodes/DataTable/DataTableExport'
import { ActorType, ExporterFormat, PropertiesTimelineFilterType, PropertyDefinitionType } from '~/types'

import { cleanedInsightActorsQueryOptions } from './persons-modal-utils'
import { PersonModalLogicProps, personsModalLogic } from './personsModalLogic'
import { SaveCohortModal } from './SaveCohortModal'

interface SessionSegmentCollapseProps {
    header: React.ReactNode
    content: React.ReactNode
    isFailed?: boolean
}

function SessionSegmentCollapse({ header, content, isFailed }: SessionSegmentCollapseProps): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(false)

    return (
        <div className="border rounded">
            <div className="cursor-pointer" onClick={() => setIsExpanded(!isExpanded)}>
                <div className="p-2">
                    <div className="flex items-center justify-between">
                        {header}
                        <IconChevronDown className={`w-4 h-4 transition-transform ${isExpanded ? 'rotate-180' : ''}`} />
                    </div>
                </div>
            </div>
            {isExpanded && <div className="border-t p-2">{content}</div>}
        </div>
    )
}

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
    const [activeTab, setActiveTab] = useState('people')
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

    const totalModalData: SummaryData = {
        id: 1,
        period: '2024-03-01 to 2024-03-15',
        sessionsAnalyzed: 150,
        keyInsights: 5,
        pains: 2,
        status: 'failure',
        details: {
            criticalIssues: [
                {
                    description: 'High drop-off at pricing comparison stage',
                    sessions: [
                        {
                            id: '0196d2be-108d-7a79-8048-e5234ad7bdc9',
                            timestamp: '2024-03-15 14:23:45',
                            hasRecording: true,
                            summary: 'Multiple users spend 2-3 minutes comparing plans but abandon before signup',
                        },
                        {
                            id: '0196d2be-108d-7a79-8048-e5234ad7bdc8',
                            timestamp: '2024-03-12 11:15:22',
                            hasRecording: true,
                            summary: 'Users frequently switch between plan comparison and feature pages without proceeding',
                        },
                    ],
                },
                {
                    description: 'Feature discovery confusion',
                    sessions: [
                        {
                            id: '0196d2bd-515c-7230-9e15-a2a437f2e3e4',
                            timestamp: '2024-03-10 16:30:22',
                            hasRecording: true,
                            summary: 'Users struggle to find key features during initial exploration',
                        },
                    ],
                },
            ],
            commonJourneys: [
                {
                    name: 'Pricing Research Pattern',
                    path: 'Homepage → Features → Pricing → Plan Comparison → Exit',
                },
                {
                    name: 'Feature Exploration Pattern',
                    path: 'Homepage → Documentation → Features → Pricing → Exit',
                },
                {
                    name: 'Quick Exit Pattern',
                    path: 'Homepage → Features → Exit',
                },
            ],
            edgeCases: [
                {
                    description: 'Users comparing multiple pricing tiers',
                    sessions: [
                        {
                            id: '0196d2bd-515c-7230-9e15-a2a437f2e3e5',
                            timestamp: '2024-03-11 09:45:12',
                            hasRecording: true,
                            summary: 'Users frequently switch between different pricing tiers without clear decision criteria',
                        },
                    ],
                },
                {
                    description: 'Feature comparison across competitors',
                    sessions: [
                        {
                            id: '0196d2bd-515c-7230-9e15-a2a437f2e3e6',
                            timestamp: '2024-03-13 15:20:33',
                            hasRecording: true,
                            summary: 'Users actively compare features with competitor products during signup process',
                        },
                    ],
                },
            ],
            summary: 'Users struggle with feature discovery, get stuck in pricing comparison, and fail to complete signup. High drop-off rates at key decision points indicate poor funnel optimization. Immediate action needed to simplify pricing presentation, improve feature visibility, and add clear decision-making guidance.',
        },
    }

    return (
        <>
            <LemonModal
                data-attr="persons-modal"
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
                <div className="px-4 py-2">
                    <LemonTabs
                        activeKey={activeTab}
                        onChange={(key) => setActiveTab(key)}
                        tabs={[
                            {
                                key: 'people',
                                label: 'People',
                                content: (
                                    <>
                                        <div className="pb-2">
                                            {actorsResponse && !!missingActorsCount && !hasGroups && (
                                                <MissingPersonsAlert
                                                    actorLabel={actorLabel}
                                                    missingActorsCount={missingActorsCount}
                                                />
                                            )}
                                            <LemonInput
                                                type="search"
                                                placeholder={
                                                    hasGroups
                                                        ? 'Search for groups by name or ID'
                                                        : 'Search for persons by email, name, or ID'
                                                }
                                                fullWidth
                                                value={searchTerm}
                                                onChange={setSearchTerm}
                                                className="mb-4 mt-2"
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
                                                cleanedInsightActorsQueryOptions(insightActorsQueryOptions, query).map(
                                                    ([key, options]) =>
                                                        key === 'breakdowns'
                                                            ? options.map(({ values }, index) => (
                                                                  <div key={`${key}_${index}`}>
                                                                      <LemonSelect
                                                                          fullWidth
                                                                          className="mb-2"
                                                                          value={query?.breakdown?.[index] ?? null}
                                                                          onChange={(v) => {
                                                                              const breakdown = Array.isArray(
                                                                                  query.breakdown
                                                                              )
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
                                                                          onChange={(v) =>
                                                                              updateActorsQuery({ [key]: v })
                                                                          }
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
                                                        {actorsResponse?.next || actorsResponse?.offset
                                                            ? 'More than '
                                                            : ''}
                                                        <b>
                                                            {totalActorsCount || 'No'} unique{' '}
                                                            {pluralize(
                                                                totalActorsCount,
                                                                actorLabel.singular,
                                                                actorLabel.plural,
                                                                false
                                                            )}
                                                        </b>
                                                    </span>
                                                )}
                                            </div>
                                        </div>
                                        <div className="overflow-hidden flex flex-col">
                                            <div className="relative min-h-20 p-2 deprecated-space-y-2 rounded bg-border-light overflow-y-auto mb-2">
                                                {errorObject ? (
                                                    validationError ? (
                                                        <InsightValidationError
                                                            query={query}
                                                            detail={validationError}
                                                        />
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
                                                                    actor.type == 'person' &&
                                                                    currentTeam?.person_on_events_querying_enabled
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
                                                    <div
                                                        className="text-center p-5"
                                                        data-attr="persons-modal-no-matches"
                                                    >
                                                        We couldn't find any matching {actorLabel.plural} for this data
                                                        point.
                                                    </div>
                                                )}

                                                {(actorsResponse?.next || actorsResponse?.offset) && (
                                                    <div className="m-4 flex justify-center">
                                                        <LemonButton
                                                            type="primary"
                                                            onClick={loadNextActors}
                                                            loading={actorsResponseLoading}
                                                        >
                                                            Load more {actorLabel.plural}
                                                        </LemonButton>
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    </>
                                ),
                            },
                            {
                                key: 'summary',
                                label: 'Summary',
                                content: <PersonSummariesTable data={totalModalData} />,
                            },
                        ]}
                    />
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
                                    type="primary"
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
                                    Explore
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

    const personModalData: SummaryData = {
        id: 1,
        period: '2024-03-01 to 2024-03-15',
        sessionsAnalyzed: 10,
        keyInsights: 3,
        pains: 1,
        status: 'failure',
        details: {
            criticalIssues: [
                {
                    description: 'Repeatedly abandons upgrade flow after viewing pricing',
                    sessions: [
                        {
                            id: '0196d2be-108d-7a79-8048-e5234ad7bdc9',
                            timestamp: '2024-03-15 14:23:45',
                            hasRecording: true,
                            summary: 'User viewed pricing page for 2 minutes, then closed the modal without upgrading.',
                        },
                        {
                            id: '0196d2be-108d-7a79-8048-e5234ad7bdc8',
                            timestamp: '2024-03-12 11:15:22',
                            hasRecording: true,
                            summary: 'User compared different plan tiers for 3 minutes, then navigated away.',
                        },
                    ],
                },
            ],
            commonJourneys: [
                {
                    name: 'Pricing Research Pattern',
                    path: 'Dashboard → Billing → View Plans → Compare Features → Close',
                },
                {
                    name: 'Regular Usage Pattern',
                    path: 'Login → Dashboard → Analytics → Export Data → Logout',
                },
            ],
            edgeCases: [
                {
                    description: 'Consistently uses free tier features despite frequent pricing checks',
                    sessions: [
                        {
                            id: '0196d2bd-515c-7230-9e15-a2a437f2e3e4',
                            timestamp: '2024-03-10 16:30:22',
                            hasRecording: true,
                            summary:
                                'User reached free tier limits, viewed upgrade options, but continued using free features.',
                        },
                    ],
                },
            ],
            summary: 'User shows strong interest in paid features but consistently abandons upgrade process. Despite multiple pricing page visits and feature comparisons, fails to complete signup. Immediate intervention needed to understand and address conversion blockers.',
        },
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
                                <IconAIText className="ml-1 mt-1 text-md" />
                            </div>
                            {actor.distinct_ids?.[0] && (
                                <CopyToClipboardInline
                                    explicitValue={actor.distinct_ids[0]}
                                    iconStyle={{ color: 'var(--accent)' }}
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
                            {
                                key: 'summary',
                                label: 'Summary',
                                content: (
                                    <div className="px-4 pb-2 pt-4 bg-bg-light">
                                        <PersonSummariesTable data={personModalData} />
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

interface Session {
    id: string
    timestamp: string
    hasRecording: boolean
    summary: string
}

interface SummaryData {
    id: number
    period: string
    sessionsAnalyzed: number
    keyInsights: number
    pains: number
    status: 'success' | 'failure'
    details: {
        criticalIssues: Array<{
            description: string
            sessions: Array<Session>
        }>
        commonJourneys: Array<{
            name: string
            path: string
        }>
        edgeCases: Array<{
            description: string
            sessions: Array<Session>
        }>
        summary: string
    }
}

export function PersonSummariesTable({ data }: { data: SummaryData }): JSX.Element {
    return (
        <div>
            <div className="flex flex-col">
                <div className="mb-2">
                    <LemonBanner type={data.status === 'success' ? 'success' : 'error'} className="mb-4">
                        <div className="text-sm font-normal">
                            <div>{data.details.summary}</div>
                        </div>
                    </LemonBanner>
                    <LemonDivider />
                </div>

                <div className="space-y-8">
                    <div>
                        <div className="flex items-center gap-2 mb-4">
                            <h4 className="text-lg font-semibold m-0">Critical Issues</h4>
                            <LemonTag type="danger" size="small">
                                {data.details.criticalIssues.length} issues
                            </LemonTag>
                        </div>
                        <div className="space-y-2">
                            {data.details.criticalIssues.map((issue, i) => (
                                <SessionSegmentCollapse
                                    key={i}
                                    isFailed={true}
                                    header={
                                        <div className="flex flex-row gap-2 items-center">
                                            <h3 className="text-sm font-medium mb-0">{issue.description}</h3>
                                            <LemonTag size="small" type="default">
                                                {issue.sessions.length} sessions
                                            </LemonTag>
                                        </div>
                                    }
                                    content={
                                        <div className="space-y-0">
                                            {issue.sessions.map((session: Session, j: number) => (
                                                <div key={j}>
                                                    <div className="text-sm py-2">
                                                        <div className="flex items-center justify-between mb-1">
                                                            <div className="flex items-center gap-2">
                                                                <span className="text-muted">{session.timestamp}</span>
                                                            </div>
                                                            <div className="flex gap-1">
                                                                <LemonButton
                                                                    sideIcon={<IconTarget />}
                                                                    size="xsmall"
                                                                    type="secondary"
                                                                >
                                                                    <span>View moment</span>
                                                                </LemonButton>
                                                                <LemonButton
                                                                    sideIcon={<IconPlayCircle />}
                                                                    size="xsmall"
                                                                    type="secondary"
                                                                >
                                                                    View recording
                                                                </LemonButton>
                                                            </div>
                                                        </div>
                                                        <p className="mb-0">{session.summary}</p>
                                                    </div>
                                                    {j < issue.sessions.length - 1 && (
                                                        <div className="h-px bg-border" />
                                                    )}
                                                </div>
                                            ))}
                                        </div>
                                    }
                                />
                            ))}
                        </div>
                    </div>

                    <div>
                        <div className="flex items-center gap-2 mb-4">
                            <h4 className="text-lg font-semibold m-0">Common User Journeys</h4>
                            <LemonTag type="default" size="small">
                                {data.details.commonJourneys.length} patterns
                            </LemonTag>
                        </div>
                        <div className="space-y-4">
                            {data.details.commonJourneys.map((journey, i) => (
                                <div key={i} className="bg-bg-light border rounded p-3">
                                    <div className="flex items-center gap-2 mb-2">
                                        <h3 className="text-sm font-medium mb-0">{journey.name}</h3>
                                        <LemonTag size="small" type="default">
                                            common
                                        </LemonTag>
                                    </div>
                                    <div className="flex items-center gap-1 text-sm">
                                        {journey.path.split(' → ').map((step, j) => (
                                            <React.Fragment key={j}>
                                                {j > 0 && <IconChevronDown className="w-4 h-4 rotate-270 text-muted" />}
                                                <span className="text-muted">{step}</span>
                                            </React.Fragment>
                                        ))}
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>

                    <div className="mb-4">
                        <div className="flex items-center gap-2 mb-4">
                            <h4 className="text-lg font-semibold m-0">Interesting Edge Cases</h4>
                            <LemonTag type="default" size="small">
                                {data.details.edgeCases.length} cases
                            </LemonTag>
                        </div>
                        <div className="space-y-2">
                            {data.details.edgeCases.map((edgeCase, i) => (
                                <SessionSegmentCollapse
                                    key={i}
                                    header={
                                        <div className="flex flex-row gap-2 items-center">
                                            <h3 className="text-sm font-medium mb-0">{edgeCase.description}</h3>
                                            <LemonTag size="small" type="default">
                                                {edgeCase.sessions.length} sessions
                                            </LemonTag>
                                        </div>
                                    }
                                    content={
                                        <div className="space-y-0">
                                            {edgeCase.sessions.map((session: Session, j: number) => (
                                                <div key={j}>
                                                    <div className="text-sm py-2">
                                                        <div className="flex items-center justify-between mb-1">
                                                            <div className="flex items-center gap-2">
                                                                <span className="text-muted">{session.timestamp}</span>
                                                                <span className="text-muted">•</span>
                                                                <span className="text-muted">{session.id}</span>
                                                            </div>
                                                            <div className="flex gap-1">
                                                                <LemonButton
                                                                    sideIcon={<IconTarget />}
                                                                    size="xsmall"
                                                                    type="secondary"
                                                                >
                                                                    <span>View moment</span>
                                                                </LemonButton>
                                                                <LemonButton
                                                                    sideIcon={<IconPlayCircle />}
                                                                    size="xsmall"
                                                                    type="secondary"
                                                                >
                                                                    View recording
                                                                </LemonButton>
                                                            </div>
                                                        </div>
                                                        <p className="mb-0">{session.summary}</p>
                                                    </div>
                                                    {j < edgeCase.sessions.length - 1 && (
                                                        <div className="h-px bg-border" />
                                                    )}
                                                </div>
                                            ))}
                                        </div>
                                    }
                                />
                            ))}
                        </div>
                    </div>
                </div>
            </div>
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
            because they've been merged with those listed, or deleted.{' '}
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
