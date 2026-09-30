import { useActions, useValues } from 'kea'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { membersLogic } from 'scenes/organization/membersLogic'

import { MemberSelectRow } from './MemberSelectRow'

const NO_EXCLUDED_MEMBERS: number[] = []

type DockedRow = { id: number; height: number }
type Docks = { top: DockedRow[]; bottom: DockedRow[] }

function dockedAtEdge(rows: DockedRow[], maxHeight: number, gap: number, edge: 'top' | 'bottom'): DockedRow[] {
    const closestFirst = edge === 'top' ? rows.reverse() : rows
    const docked: DockedRow[] = []
    let height = 0
    for (const row of closestFirst) {
        if (height + row.height > maxHeight) {
            break
        }
        docked.push(row)
        height += row.height + gap
    }
    return edge === 'top' ? docked.reverse() : docked
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
    const [dockableIds, setDockableIds] = useState(() => new Set(value))
    const [docks, setDocks] = useState<Docks>({ top: [], bottom: [] })
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
            setDockableIds(new Set(value))
            return
        }
        const timeout = setTimeout(() => setDockableIds(new Set(value)), remainingDelay)
        return () => clearTimeout(timeout)
    }, [value, pointerOverList])

    const members = useMemo(() => selectableMembers(excludedMembers, 'id'), [selectableMembers, excludedMembers])

    useLayoutEffect(() => {
        const scrollArea = scrollRef.current
        const list = listRef.current
        if (!scrollArea || !list) {
            return
        }

        const updateDocks = (): void => {
            let next: Docks = { top: [], bottom: [] }
            if (!search && list.scrollHeight > scrollArea.clientHeight) {
                const rows = Array.from(list.children) as HTMLElement[]
                const gap = Number.parseFloat(getComputedStyle(list).rowGap) || 0
                const maxEdgeHeight = (scrollArea.parentElement?.clientHeight || scrollArea.clientHeight) / 3
                const above: DockedRow[] = []
                const below: DockedRow[] = []
                let offset = 0

                for (const [index, member] of members.entries()) {
                    const height = rows[index]?.offsetHeight ?? 0
                    if (dockableIds.has(member.user.id)) {
                        const naturalTop = offset - scrollArea.scrollTop
                        if (naturalTop + height <= 0) {
                            above.push({ id: member.user.id, height })
                        } else if (naturalTop >= scrollArea.clientHeight) {
                            below.push({ id: member.user.id, height })
                        }
                    }
                    offset += height + gap
                }

                next = {
                    top: dockedAtEdge(above, maxEdgeHeight, gap, 'top'),
                    bottom: dockedAtEdge(below, maxEdgeHeight, gap, 'bottom'),
                }
            }
            setDocks((current) => (JSON.stringify(current) === JSON.stringify(next) ? current : next))
        }

        updateDocks()
        scrollArea.addEventListener('scroll', updateDocks, { passive: true })
        const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(updateDocks)
        observer?.observe(scrollArea)
        observer?.observe(list)
        return () => {
            scrollArea.removeEventListener('scroll', updateDocks)
            observer?.disconnect()
        }
    }, [dockableIds, search, members, membersLoading])

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

    const renderRow = (member: (typeof members)[number]): JSX.Element => (
        <MemberSelectRow
            key={member.user.uuid}
            member={member}
            isYou={member.user.uuid === me?.user.uuid}
            onClick={() => toggleMember(member.user.id)}
            checked={value.includes(member.user.id)}
        />
    )
    const memberById = new Map(members.map((member) => [member.user.id, member]))
    const dockedHeights = new Map([...docks.top, ...docks.bottom].map((row) => [row.id, row.height]))

    const renderDock = (rows: DockedRow[], label: string, edge: 'top' | 'bottom'): JSX.Element | null => {
        const dockedMembers = rows.flatMap((row) => {
            const member = memberById.get(row.id)
            return member ? [member] : []
        })
        return dockedMembers.length ? (
            <ul className={`flex flex-col gap-px ${edge === 'top' ? 'border-b' : 'border-t'}`} aria-label={label}>
                {dockedMembers.map(renderRow)}
            </ul>
        ) : null
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
                className="flex max-h-80 flex-col"
                onMouseEnter={() => setPointerOverList(true)}
                onMouseLeave={() => setPointerOverList(false)}
            >
                {renderDock(docks.top, 'Selected members above', 'top')}
                <div
                    ref={scrollRef}
                    className="min-h-0 flex-1 overflow-y-auto"
                    onScroll={() =>
                        setDockableIds((current) =>
                            current.size === value.length && value.every((id) => current.has(id))
                                ? current
                                : new Set(value)
                        )
                    }
                >
                    <ul ref={listRef} className="flex flex-col gap-px" aria-label="Members">
                        {members.map((member) =>
                            dockedHeights.has(member.user.id) ? (
                                <li
                                    key={member.user.uuid}
                                    aria-hidden="true"
                                    style={{ height: dockedHeights.get(member.user.id) }}
                                />
                            ) : (
                                renderRow(member)
                            )
                        )}
                        {membersLoading ? (
                            <li className="p-2 text-secondary italic truncate border-t">Loading...</li>
                        ) : members.length === 0 ? (
                            <li className="p-2 text-secondary italic truncate border-t">
                                {search ? 'No matches' : 'No users'}
                            </li>
                        ) : null}
                    </ul>
                </div>
                {renderDock(docks.bottom, 'Selected members below', 'bottom')}
            </div>
        </div>
    )
}
