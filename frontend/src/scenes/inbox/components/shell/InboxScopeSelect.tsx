import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { IconAsterisk, IconCheck, IconChevronDown } from '@posthog/icons'
import { LemonDropdown, LemonInput } from '@posthog/lemon-ui'

import api from 'lib/api'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture/ProfilePicture'

import { isTeammateInboxScope, parseTeammateInboxScope, teammateInboxScope } from '../../inboxMembership'
import { inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { INBOX_SCOPE_ENTIRE_PROJECT, INBOX_SCOPE_FOR_YOU, InboxScope } from '../../types'

interface AvailableReviewer {
    user_uuid: string
    name: string
    email: string
}

/**
 * Two-segment scope toggle. Left segment is "For you"; the right segment shows
 * "Entire project" or the selected teammate's name, and opens a searchable people
 * picker ("Entire project" + each teammate, with avatars). One-to-one port of
 * desktop `InboxScopeSelect` (segmented control + combobox), in LemonUI. Scope is
 * persisted via `inboxFiltersLogic`; teammates come from `available_reviewers`.
 */
export function InboxScopeSelect(): JSX.Element {
    const { scope } = useValues(inboxFiltersLogic)
    const { setScope } = useActions(inboxFiltersLogic)
    const [reviewers, setReviewers] = useState<AvailableReviewer[]>([])
    const [open, setOpen] = useState(false)
    const [search, setSearch] = useState('')

    useEffect(() => {
        let cancelled = false
        void api.signalReports
            .availableReviewers()
            .then((response) => {
                if (!cancelled) {
                    setReviewers(
                        response.results.map((r) => ({ user_uuid: r.user_uuid, name: r.name, email: r.email }))
                    )
                }
            })
            .catch(() => {
                // Non-fatal: the picker still offers "For you" / "Entire project".
            })
        return () => {
            cancelled = true
        }
    }, [])

    const isForYou = scope === INBOX_SCOPE_FOR_YOU
    const selectedTeammateUuid = isTeammateInboxScope(scope) ? parseTeammateInboxScope(scope) : null
    const selectedTeammate = reviewers.find((r) => r.user_uuid === selectedTeammateUuid)
    const rightLabel = selectedTeammate ? selectedTeammate.name || selectedTeammate.email : 'Entire project'

    const filteredReviewers = useMemo(() => {
        const q = search.trim().toLowerCase()
        if (!q) {
            return reviewers
        }
        return reviewers.filter((r) => `${r.name} ${r.email}`.toLowerCase().includes(q))
    }, [reviewers, search])

    const pick = (next: InboxScope): void => {
        setScope(next)
        setOpen(false)
        setSearch('')
    }

    return (
        <LemonDropdown
            visible={open}
            onVisibilityChange={setOpen}
            closeOnClickInside={false}
            matchWidth={false}
            placement="bottom-end"
            overlay={
                <div className="w-[240px] p-1">
                    <LemonInput
                        type="search"
                        size="small"
                        placeholder="Search people…"
                        value={search}
                        onChange={setSearch}
                        autoFocus
                        className="mb-1"
                    />
                    <div className="max-h-[16rem] overflow-y-auto space-y-px">
                        <ScopeRow
                            active={scope === INBOX_SCOPE_ENTIRE_PROJECT}
                            onClick={() => pick(INBOX_SCOPE_ENTIRE_PROJECT)}
                            avatar={
                                <span
                                    className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-dashed border-secondary text-tertiary"
                                    aria-hidden
                                >
                                    <IconAsterisk className="text-xs" />
                                </span>
                            }
                            label="Entire project"
                        />
                        {filteredReviewers.map((reviewer) => (
                            <ScopeRow
                                key={reviewer.user_uuid}
                                active={selectedTeammateUuid === reviewer.user_uuid}
                                onClick={() => pick(teammateInboxScope(reviewer.user_uuid))}
                                avatar={
                                    <ProfilePicture
                                        user={{ first_name: reviewer.name, email: reviewer.email }}
                                        size="sm"
                                    />
                                }
                                label={reviewer.name || reviewer.email}
                            />
                        ))}
                        {filteredReviewers.length === 0 && (
                            <div className="px-2 py-1.5 text-xs text-tertiary">No matching people.</div>
                        )}
                    </div>
                </div>
            }
        >
            <div className="inline-flex h-8 items-center overflow-hidden rounded-md border border-primary bg-surface-primary text-sm">
                <button
                    type="button"
                    onClick={() => {
                        setScope(INBOX_SCOPE_FOR_YOU)
                        setOpen(false)
                    }}
                    className={clsx(
                        'h-full px-2.5 transition-colors',
                        isForYou
                            ? 'bg-fill-primary font-medium text-default'
                            : 'text-secondary hover:bg-surface-secondary'
                    )}
                >
                    For you
                </button>
                <div className="h-full w-px bg-border" />
                <button
                    type="button"
                    onClick={() => setOpen((v) => !v)}
                    aria-haspopup="listbox"
                    aria-expanded={open}
                    className={clsx(
                        'inline-flex h-full items-center gap-1 px-2.5 transition-colors',
                        !isForYou
                            ? 'bg-fill-primary font-medium text-default'
                            : 'text-secondary hover:bg-surface-secondary'
                    )}
                >
                    <span className="max-w-[160px] truncate">{rightLabel}</span>
                    <IconChevronDown className="text-xs text-tertiary" />
                </button>
            </div>
        </LemonDropdown>
    )
}

function ScopeRow({
    active,
    onClick,
    avatar,
    label,
}: {
    active: boolean
    onClick: () => void
    avatar: JSX.Element
    label: string
}): JSX.Element {
    return (
        <button
            type="button"
            onClick={onClick}
            className={clsx(
                'flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm transition-colors',
                active ? 'bg-surface-secondary font-medium' : 'hover:bg-surface-secondary'
            )}
        >
            {avatar}
            <span className="min-w-0 flex-1 truncate">{label}</span>
            {active && <IconCheck className="shrink-0 text-sm text-default" />}
        </button>
    )
}
