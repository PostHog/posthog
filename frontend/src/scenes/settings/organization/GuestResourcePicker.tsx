import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef, useState } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonSelect } from '@posthog/lemon-ui'

import api from 'lib/api'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInputSelect, LemonInputSelectOption } from 'lib/lemon-ui/LemonInputSelect'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { GuestInviteGrant, inviteLogic } from './inviteLogic'

type ResourceType = 'notebook'

// Editor-level guest grants are blocked at the invite API; the picker only emits viewer
// grants today. The data model still carries `access_level` per grant — when the admin
// "edit guest grants" flow ships, this picker will surface a per-grant level toggle and
// the API will lift its rejection.
const SEARCH_DEBOUNCE_MS = 250
const SEARCH_RESULT_LIMIT = 20

function useResourceOptions(
    resourceType: ResourceType,
    teamId: number | null,
    searchQuery: string
): { options: LemonInputSelectOption[]; loading: boolean } {
    const [options, setOptions] = useState<LemonInputSelectOption[]>([])
    const [loading, setLoading] = useState(false)
    // One toast per (teamId, resourceType) pair on failure — keeps the admin informed
    // without hammering the screen with toasts on every keystroke.
    const toastedKeyRef = useRef<string | null>(null)

    useEffect(() => {
        if (!teamId) {
            setOptions([])
            setLoading(false)
            return
        }
        let cancelled = false
        setLoading(true)

        const debounce = setTimeout(() => {
            if (cancelled) {
                return
            }
            const fetchResources = async (): Promise<void> => {
                const trimmed = searchQuery.trim()
                const searchParam = trimmed ? `&search=${encodeURIComponent(trimmed)}` : ''
                const url = `api/projects/${teamId}/${resourceType}s/?limit=${SEARCH_RESULT_LIMIT}${searchParam}`
                try {
                    const response = await api.get(url)
                    if (cancelled) {
                        return
                    }
                    const results = response.results ?? []
                    setOptions(
                        results.map((n: any) => ({
                            key: String(n.short_id),
                            label: n.title || `Notebook ${n.short_id}`,
                        }))
                    )
                    toastedKeyRef.current = null
                } catch {
                    if (cancelled) {
                        return
                    }
                    setOptions([])
                    const toastKey = `${teamId}:${resourceType}`
                    if (toastedKeyRef.current !== toastKey) {
                        lemonToast.error(`Couldn't load ${resourceType}s for the selected project.`)
                        toastedKeyRef.current = toastKey
                    }
                } finally {
                    if (!cancelled) {
                        setLoading(false)
                    }
                }
            }
            void fetchResources()
        }, SEARCH_DEBOUNCE_MS)

        return () => {
            cancelled = true
            clearTimeout(debounce)
        }
    }, [resourceType, teamId, searchQuery])

    return { options, loading }
}

export function GuestResourcePicker(): JSX.Element {
    const { guestGrants, availableProjects } = useValues(inviteLogic)
    const { addGuestGrant, removeGuestGrant } = useActions(inviteLogic)
    const { currentTeamId } = useValues(teamLogic)

    const [resourceType, setResourceType] = useState<ResourceType>('notebook')
    const [selectedKey, setSelectedKey] = useState<string[]>([])
    const [searchQuery, setSearchQuery] = useState('')
    const [pickerTeamId, setPickerTeamId] = useState<number | null>(
        currentTeamId ?? (availableProjects[0]?.id as number | undefined) ?? null
    )

    const { options, loading } = useResourceOptions(resourceType, pickerTeamId, searchQuery)

    const projectNameById = useMemo(() => {
        const map = new Map<number, string>()
        availableProjects.forEach((p: any) => map.set(p.id, p.name))
        return map
    }, [availableProjects])

    // Preserve the order in which projects appear in the grants list, so the grouped
    // Selected view doesn't shuffle when the admin adds a second resource to an
    // already-listed project.
    const groupedGrants = useMemo(() => {
        const groups: { teamId: number; entries: { grant: GuestInviteGrant; index: number }[] }[] = []
        const indexByTeam = new Map<number, number>()
        guestGrants.forEach((grant: GuestInviteGrant, index: number) => {
            let groupIdx = indexByTeam.get(grant.team_id)
            if (groupIdx === undefined) {
                groupIdx = groups.length
                indexByTeam.set(grant.team_id, groupIdx)
                groups.push({ teamId: grant.team_id, entries: [] })
            }
            groups[groupIdx].entries.push({ grant, index })
        })
        return groups
    }, [guestGrants])

    const handleAdd = (): void => {
        if (!selectedKey[0] || !pickerTeamId) {
            return
        }
        const key = selectedKey[0]
        const option = options.find((o) => o.key === key)
        if (!option) {
            return
        }
        addGuestGrant({
            team_id: pickerTeamId,
            resource: resourceType,
            resource_id: key,
            label: typeof option.label === 'string' ? option.label : key,
            // access_level omitted — reducer defaults to viewer.
        })
        setSelectedKey([])
    }

    // Single-resource picker today; the dashboard / insight options come back in the
    // dashboard / insight follow-up PR.
    const resourceOptions: { value: ResourceType; label: string }[] = [{ value: 'notebook', label: 'Notebook' }]

    const projectOptions = availableProjects.map((p: any) => ({ value: p.id as number, label: p.name as string }))
    const showProjectPicker = availableProjects.length > 1

    return (
        <div className="space-y-3" data-attr="guest-resource-picker">
            {showProjectPicker && (
                <div className="space-y-1">
                    <div className="text-sm font-medium">Browse from project</div>
                    <LemonSelect<number>
                        options={projectOptions}
                        value={pickerTeamId ?? undefined}
                        onChange={(v) => {
                            if (typeof v === 'number') {
                                setPickerTeamId(v)
                                setSelectedKey([])
                                setSearchQuery('')
                            }
                        }}
                        className="min-w-64"
                        data-attr="guest-resource-project-picker"
                    />
                </div>
            )}
            <div className="space-y-1">
                <div className="text-sm font-medium">Resources</div>
                <div className="flex gap-2 items-center">
                    <LemonSelect
                        options={resourceOptions}
                        value={resourceType}
                        onChange={(v) => {
                            if (v) {
                                setResourceType(v)
                                setSelectedKey([])
                                setSearchQuery('')
                            }
                        }}
                        className="shrink-0"
                    />
                    <div className="flex-1">
                        <LemonInputSelect
                            mode="single"
                            placeholder={loading ? 'Loading…' : `Search ${resourceType}s…`}
                            loading={loading}
                            options={options}
                            value={selectedKey}
                            onChange={setSelectedKey}
                            onInputChange={setSearchQuery}
                            disableFiltering
                        />
                    </div>
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={handleAdd}
                        disabledReason={
                            !pickerTeamId
                                ? 'Pick a project first'
                                : !selectedKey[0]
                                  ? 'Select a resource first'
                                  : undefined
                        }
                        data-attr="guest-resource-add"
                    >
                        Add
                    </LemonButton>
                </div>
            </div>

            {groupedGrants.length > 0 && (
                <div className="space-y-2" data-attr="guest-grants-list">
                    <div className="text-sm font-medium">Selected ({guestGrants.length})</div>
                    <div className="bg-bg-light rounded border divide-y">
                        {groupedGrants.map(({ teamId, entries }) => (
                            <div key={teamId} className="p-2 space-y-1" data-attr={`guest-grants-group-${teamId}`}>
                                <div className="text-xs font-medium text-muted-alt">
                                    {projectNameById.get(teamId) ?? `Project ${teamId}`}
                                </div>
                                {entries.map(({ grant, index }) => (
                                    <div
                                        key={index}
                                        className="flex items-center gap-2 pl-2"
                                        data-attr={`guest-grant-row-${index}`}
                                    >
                                        <span className="text-xs text-muted capitalize w-16 shrink-0">
                                            {grant.resource}
                                        </span>
                                        <span className="flex-1 text-sm">{grant.label || grant.resource_id}</span>
                                        <LemonButton
                                            size="small"
                                            icon={<IconTrash />}
                                            status="danger"
                                            onClick={() => removeGuestGrant(index)}
                                        />
                                    </div>
                                ))}
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    )
}
