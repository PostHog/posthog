import { useActions, useValues } from 'kea'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { membersLogic } from 'scenes/organization/membersLogic'

import { MemberSelectRow } from './MemberSelectRow'

const NO_EXCLUDED_MEMBERS: number[] = []

type StickyRow = { id: number; height: number }
type StickyOffset = { top?: number; bottom?: number }

function edgeOffsets(
    rows: StickyRow[],
    maxHeight: number,
    gap: number,
    edge: 'top' | 'bottom'
): Record<number, StickyOffset> {
    const closestFirst = edge === 'top' ? rows.reverse() : rows
    const pinned: StickyRow[] = []
    let height = 0
    for (const row of closestFirst) {
        if (height + row.height > maxHeight) {
            break
        }
        pinned.push(row)
        height += row.height + gap
    }

    const offsets: Record<number, StickyOffset> = {}
    let offset = 0
    for (const row of pinned.reverse()) {
        offsets[row.id] = edge === 'top' ? { top: offset } : { bottom: offset }
        offset += row.height + gap
    }
    return offsets
}

export type MemberSelectMultipleOptionsProps = {
    /** Currently selected member user ids. */
    value: number[]
    onChange: (value: number[]) => void
    /** Member user ids to leave out of the list. */
    excludedMembers?: number[]
}

export function MemberSelectMultipleOptions({
    value,
    onChange,
    excludedMembers = NO_EXCLUDED_MEMBERS,
}: MemberSelectMultipleOptionsProps): JSX.Element {
    const { me, selectableMembers, membersLoading, search } = useValues(membersLogic)
    const { setSearch } = useActions(membersLogic)
    const [stickyIds, setStickyIds] = useState(() => new Set(value))
    const [pinnedRows, setPinnedRows] = useState<Record<number, StickyOffset>>({})
    const [pointerOverList, setPointerOverList] = useState(false)
    const lastSelectionAt = useRef(Date.now())
    const scrollRef = useRef<HTMLDivElement>(null)
    const listRef = useRef<HTMLUListElement>(null)

    useEffect(() => {
        if (pointerOverList) {
            return
        }
        const remainingDelay = Math.max(0, 600 - (Date.now() - lastSelectionAt.current))
        if (remainingDelay === 0) {
            setStickyIds(new Set(value))
            return
        }
        const timeout = setTimeout(() => setStickyIds(new Set(value)), remainingDelay)
        return () => clearTimeout(timeout)
    }, [value, pointerOverList])

    const members = useMemo(() => selectableMembers(excludedMembers, 'id'), [selectableMembers, excludedMembers])

    useLayoutEffect(() => {
        const scrollArea = scrollRef.current
        const list = listRef.current
        if (!scrollArea || !list) {
            return
        }

        const updatePinnedRows = (): void => {
            let next: Record<number, StickyOffset> = {}
            if (!search && list.scrollHeight > scrollArea.clientHeight) {
                const rows = Array.from(list.children) as HTMLElement[]
                const gap = Number.parseFloat(getComputedStyle(list).rowGap) || 0
                const listTop = list.getBoundingClientRect().top - scrollArea.getBoundingClientRect().top
                const maxEdgeHeight = scrollArea.clientHeight / 3
                const above: StickyRow[] = []
                const below: StickyRow[] = []
                let offset = 0

                for (const [index, member] of members.entries()) {
                    const height = rows[index]?.offsetHeight ?? 0
                    if (stickyIds.has(member.user.id)) {
                        const naturalTop = listTop + offset
                        if (naturalTop < maxEdgeHeight) {
                            above.push({ id: member.user.id, height })
                        } else if (naturalTop + height > scrollArea.clientHeight - maxEdgeHeight) {
                            below.push({ id: member.user.id, height })
                        }
                    }
                    offset += height + gap
                }

                next = {
                    ...edgeOffsets(above, maxEdgeHeight, gap, 'top'),
                    ...edgeOffsets(below, maxEdgeHeight, gap, 'bottom'),
                }
            }
            setPinnedRows((current) => (JSON.stringify(current) === JSON.stringify(next) ? current : next))
        }

        updatePinnedRows()
        scrollArea.addEventListener('scroll', updatePinnedRows, { passive: true })
        const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(updatePinnedRows)
        observer?.observe(scrollArea)
        observer?.observe(list)
        return () => {
            scrollArea.removeEventListener('scroll', updatePinnedRows)
            observer?.disconnect()
        }
    }, [stickyIds, search, members, membersLoading])

    const toggleMember = (userId: number): void => {
        const selected = new Set(value)
        if (selected.has(userId)) {
            selected.delete(userId)
        } else {
            selected.add(userId)
        }
        lastSelectionAt.current = Date.now()
        onChange(Array.from(selected))
    }

    return (
        <div className="max-w-100 flex flex-col gap-2">
            <LemonInput type="search" placeholder="Search" autoFocus value={search} onChange={setSearch} fullWidth />
            <LemonButton
                data-attr="member-filter-clear-selection"
                fullWidth
                role="menuitem"
                size="small"
                type="tertiary"
                icon={<IconX />}
                disabledReason={value.length === 0 ? 'No members selected' : undefined}
                onClick={() => onChange([])}
            >
                Clear selection
            </LemonButton>
            <div
                ref={scrollRef}
                className="max-h-80 overflow-y-auto flex flex-col gap-px"
                onScroll={() =>
                    setStickyIds((current) =>
                        current.size === value.length && value.every((id) => current.has(id)) ? current : new Set(value)
                    )
                }
                onMouseEnter={() => setPointerOverList(true)}
                onMouseLeave={() => setPointerOverList(false)}
            >
                <ul ref={listRef} className="flex flex-col gap-px" aria-label="Members">
                    {members.map((member) => (
                        <MemberSelectRow
                            key={member.user.uuid}
                            member={member}
                            isYou={member.user.uuid === me?.user.uuid}
                            onClick={() => toggleMember(member.user.id)}
                            checked={value.includes(member.user.id)}
                            stickyStyle={pinnedRows[member.user.id]}
                        />
                    ))}
                    {membersLoading ? (
                        <li className="p-2 text-secondary italic truncate border-t">Loading...</li>
                    ) : members.length === 0 ? (
                        <li className="p-2 text-secondary italic truncate border-t">
                            {search ? 'No matches' : 'No users'}
                        </li>
                    ) : null}
                </ul>
            </div>
        </div>
    )
}
