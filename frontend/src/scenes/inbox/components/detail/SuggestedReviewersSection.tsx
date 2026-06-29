import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconCheck, IconInfo, IconPeople, IconPlus, IconX } from '@posthog/icons'
import { LemonButton, LemonInput, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { EnrichedReviewer, SignalReport } from '../../types'

const MAX_VISIBLE_REVIEWERS = 5
import { RightColumnSection } from './DetailSection'
import {
    AvailableReviewerOption,
    getReviewerOptionDisplayName,
    reviewerMatchesOption,
    reviewersToWriteContent,
} from './reviewerDisplay'

/**
 * Suggested reviewers for the report, read from the `suggested_reviewers` artefact, with add/remove
 * editing. Mirrors desktop's `SuggestedReviewersSection`: a search popover to add org members (current
 * user pinned "Me"), per-row remove, and an optimistic update that converges on the reloaded artefact.
 */
export function SuggestedReviewersSection({ report }: { report: SignalReport }): JSX.Element | null {
    const logic = inboxReportDetailLogic({ reportId: report.id, report })
    const {
        reportReviewers,
        displayReviewers,
        addReviewerOptions,
        availableReviewersLoading,
        isUpdatingReviewers,
        reportArtefacts,
    } = useValues(logic)
    const { updateReviewers, searchAvailableReviewers } = useActions(logic)

    // The writable artefact id; without it there's nothing to PUT against, so the section can't render.
    const artefactId = useMemo(
        () => reportArtefacts?.find((a) => a.type === 'suggested_reviewers')?.id ?? null,
        [reportArtefacts]
    )

    const [addOpen, setAddOpen] = useState(false)
    const [query, setQuery] = useState('')
    const [showAllReviewers, setShowAllReviewers] = useState(false)

    const reviewers = displayReviewers
    const baseReviewers = reviewers ?? []
    // Assigned set keyed by user uuid (how `reviewerMatchesOption` matches), so the add-list
    // membership check is O(1) per option instead of scanning every reviewer per keystroke.
    const assignedUuids = useMemo(
        () => new Set(baseReviewers.map((r) => r.user?.uuid).filter(Boolean)),
        [baseReviewers]
    )
    const meUuid = addReviewerOptions[0]?.user_uuid

    // Render nothing only when there is no artefact at all (no reviewers ever computed). An empty list with
    // an artefact still renders so the user can add reviewers.
    if (!artefactId || reportReviewers === null) {
        return null
    }

    const fireAction = (
        action: 'add_suggested_reviewer' | 'remove_suggested_reviewer',
        login?: string | null
    ): void => {
        captureInboxReportAction({
            report,
            actionType: action,
            surface: 'detail_pane',
            extra: { suggested_reviewer_login: login || undefined },
        })
    }

    const removeReviewer = (target: EnrichedReviewer): void => {
        const next = baseReviewers.filter((r) => r !== target)
        fireAction('remove_suggested_reviewer', target.github_login)
        updateReviewers(artefactId, reviewersToWriteContent(next), next)
    }

    const toggleOption = (option: AvailableReviewerOption): void => {
        const existing = baseReviewers.find((r) => reviewerMatchesOption(r, option))
        if (existing) {
            removeReviewer(existing)
            return
        }
        const optimisticEntry: EnrichedReviewer = {
            github_login: '',
            github_name: option.name || null,
            relevant_commits: [],
            user: {
                id: 0,
                uuid: option.user_uuid,
                email: option.email,
                first_name: option.name,
                last_name: '',
            },
        }
        const next = [...baseReviewers, optimisticEntry]
        fireAction('add_suggested_reviewer', option.user_uuid)
        updateReviewers(artefactId, [...reviewersToWriteContent(baseReviewers), { user_uuid: option.user_uuid }], next)
    }

    return (
        <RightColumnSection
            icon={<IconPeople />}
            title="Reviewers"
            rightSlot={
                <div className="flex items-center gap-2">
                    <Tooltip title="Suggested reviewers are tracked in PostHog. To request a review on GitHub, add them on the pull request directly.">
                        <span className="-m-1 flex cursor-help items-center p-1 text-base text-tertiary">
                            <IconInfo />
                        </span>
                    </Tooltip>
                    {isUpdatingReviewers && <Spinner className="size-3" />}
                    <LemonDropdown
                        visible={addOpen}
                        onClickOutside={() => {
                            setAddOpen(false)
                            setQuery('')
                        }}
                        closeOnClickInside={false}
                        placement="bottom-end"
                        overlay={
                            <div className="flex flex-col gap-2 w-72 p-1">
                                <LemonInput
                                    type="search"
                                    size="small"
                                    autoFocus
                                    placeholder="Search users…"
                                    value={query}
                                    onChange={(value) => {
                                        setQuery(value)
                                        searchAvailableReviewers(value)
                                    }}
                                />
                                <div className="max-h-72 overflow-y-auto flex flex-col">
                                    {availableReviewersLoading ? (
                                        <span className="flex items-center gap-2 px-1 py-2 text-xs text-tertiary">
                                            <Spinner className="size-3" />
                                            Searching…
                                        </span>
                                    ) : addReviewerOptions.length === 0 ? (
                                        <span className="px-1 py-2 text-xs text-tertiary">No users found.</span>
                                    ) : (
                                        addReviewerOptions.map((option) => {
                                            const assigned = assignedUuids.has(option.user_uuid)
                                            const isMe = meUuid === option.user_uuid
                                            return (
                                                <button
                                                    key={option.user_uuid}
                                                    type="button"
                                                    disabled={isUpdatingReviewers}
                                                    className="flex w-full items-start justify-between gap-2 rounded px-1.5 py-1 text-left transition-colors hover:bg-fill-highlight-50 disabled:opacity-60"
                                                    onClick={() => toggleOption(option)}
                                                >
                                                    <div className="flex items-center gap-2 min-w-0">
                                                        <PersonDisplay
                                                            person={{
                                                                properties: {
                                                                    email: option.email,
                                                                    name: option.name,
                                                                },
                                                            }}
                                                            displayName={getReviewerOptionDisplayName(option, isMe)}
                                                            withIcon="xs"
                                                            noLink
                                                            noPopover
                                                        />
                                                    </div>
                                                    <span className="flex size-4 shrink-0 items-center justify-center text-primary">
                                                        {assigned && <IconCheck className="text-sm" />}
                                                    </span>
                                                </button>
                                            )
                                        })
                                    )}
                                </div>
                            </div>
                        }
                    >
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            icon={<IconPlus />}
                            onClick={() => setAddOpen((open) => !open)}
                        >
                            Add
                        </LemonButton>
                    </LemonDropdown>
                </div>
            }
        >
            {baseReviewers.length === 0 ? (
                <span className="text-xs text-tertiary">No reviewers assigned. Use "Add" to suggest one.</span>
            ) : (
                <div className="flex flex-col gap-1.5">
                    {(showAllReviewers ? baseReviewers : baseReviewers.slice(0, MAX_VISIBLE_REVIEWERS)).map(
                        (reviewer: EnrichedReviewer) => (
                            <ReviewerRow
                                key={reviewer.user?.uuid ?? reviewer.github_login}
                                reviewer={reviewer}
                                disabled={isUpdatingReviewers}
                                onRemove={() => removeReviewer(reviewer)}
                            />
                        )
                    )}
                    {baseReviewers.length > MAX_VISIBLE_REVIEWERS && (
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            fullWidth
                            onClick={() => setShowAllReviewers((show) => !show)}
                            className="text-tertiary"
                        >
                            {showAllReviewers ? 'Show less' : `Show all (${baseReviewers.length})`}
                        </LemonButton>
                    )}
                </div>
            )}
        </RightColumnSection>
    )
}

function ReviewerRow({
    reviewer,
    disabled,
    onRemove,
}: {
    reviewer: EnrichedReviewer
    disabled: boolean
    onRemove: () => void
}): JSX.Element {
    const displayName = reviewer.github_name ?? reviewer.user?.first_name ?? reviewer.github_login
    const reason = reviewer.relevant_commits[0]?.reason ?? null
    const githubUrl = reviewer.github_login ? `https://github.com/${reviewer.github_login}` : null

    const person = (
        <PersonDisplay
            person={{
                properties: {
                    email: reviewer.user?.email,
                    name: displayName,
                },
            }}
            displayName={displayName}
            withIcon="xs"
            noLink
            noPopover
        />
    )

    return (
        <div className="group flex items-start gap-2 rounded px-1.5 py-1.5 transition-colors hover:bg-fill-highlight-50">
            <Tooltip
                title={
                    reviewer.user
                        ? githubUrl
                            ? `@${reviewer.github_login} on GitHub`
                            : undefined
                        : `${displayName} hasn't connected their GitHub account to PostHog. Ask them to do so in Settings!`
                }
            >
                <span className={!reviewer.user ? 'opacity-75' : undefined}>
                    {/* The GitHub handle's link is merged into the name: clicking it opens the
                        reviewer's GitHub profile, flagged by the external-link icon. */}
                    {githubUrl ? (
                        <Link
                            to={githubUrl}
                            target="_blank"
                            className="inline-flex items-center gap-1 text-default hover:text-primary"
                        >
                            {person}
                        </Link>
                    ) : (
                        person
                    )}
                </span>
            </Tooltip>
            <div className="flex flex-col min-w-0 flex-1 gap-0.5">
                {reviewer.relevant_commits.length > 0 && (
                    <span className="text-[0.6875rem] text-tertiary">
                        {reviewer.relevant_commits.map((commit, i) => (
                            <span key={commit.sha}>
                                {i > 0 && ', '}
                                <Link
                                    to={commit.url}
                                    target="_blank"
                                    className="font-mono text-tertiary hover:text-primary"
                                >
                                    {commit.sha.slice(0, 7)}
                                </Link>
                            </span>
                        ))}
                    </span>
                )}
                {reason && <span className="text-[0.6875rem] text-tertiary leading-snug">{reason}</span>}
            </div>
            <LemonButton
                size="xsmall"
                type="tertiary"
                icon={<IconX />}
                disabledReason={disabled ? 'Updating…' : undefined}
                onClick={onRemove}
                tooltip={`Remove ${reviewer.github_login || reviewer.user?.first_name || 'reviewer'}`}
                className="opacity-0 transition-opacity group-hover:opacity-100"
            />
        </div>
    )
}
