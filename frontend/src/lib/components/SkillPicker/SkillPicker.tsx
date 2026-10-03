import { useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'

export interface SkillPickerSkill {
    name: string
    description: string
}

export interface SkillPickerGroup {
    key: string
    label: string
    skills: SkillPickerSkill[]
}

export interface SkillPickerProps {
    /** Skills to offer, already filtered and grouped by the caller. A group with no matches is hidden. */
    groups: SkillPickerGroup[]
    /** True while the caller is still fetching the groups' skills. */
    loading?: boolean
    /** Shown when every group is empty before any search input. */
    emptyMessage?: string
    /** Label of each row's select button. */
    selectLabel?: string
    onSelect: (skill: SkillPickerSkill) => void
    /** Lazily fetches a skill's markdown body when its preview is expanded. Omit to hide previews. */
    loadBody?: (name: string) => Promise<string>
    'data-attr'?: string
}

function matchesQuery(skill: SkillPickerSkill, query: string): boolean {
    return skill.name.toLowerCase().includes(query) || skill.description.toLowerCase().includes(query)
}

function SkillPickerRow({
    skill,
    selectLabel,
    onSelect,
    loadBody,
}: {
    skill: SkillPickerSkill
    selectLabel: string
    onSelect: (skill: SkillPickerSkill) => void
    loadBody?: (name: string) => Promise<string>
}): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const [body, setBody] = useState<string | null>(null)
    const [bodyLoading, setBodyLoading] = useState(false)
    const [bodyFailed, setBodyFailed] = useState(false)

    const fetchBody = async (): Promise<void> => {
        if (body !== null || !loadBody) {
            return
        }
        setBodyLoading(true)
        setBodyFailed(false)
        try {
            setBody(await loadBody(skill.name))
        } catch {
            setBodyFailed(true)
        } finally {
            setBodyLoading(false)
        }
    }

    const togglePreview = (): void => {
        if (expanded) {
            setExpanded(false)
            return
        }
        setExpanded(true)
        void fetchBody()
    }

    return (
        <div className="flex flex-col gap-2 rounded border border-primary p-3">
            <div className="flex items-start justify-between gap-4">
                <div className="flex min-w-0 flex-col gap-1">
                    <span className="text-sm font-semibold break-all">{skill.name}</span>
                    {skill.description ? (
                        <p className="m-0 text-xs text-secondary">{skill.description}</p>
                    ) : (
                        <p className="m-0 text-xs italic text-tertiary">No description</p>
                    )}
                    {loadBody && (
                        <div className="text-xs">
                            <Link onClick={togglePreview} data-attr="skill-picker-toggle-preview">
                                {expanded ? 'Hide preview' : 'Preview'}
                            </Link>
                        </div>
                    )}
                </div>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => onSelect(skill)}
                    data-attr="skill-picker-select"
                >
                    {selectLabel}
                </LemonButton>
            </div>
            {expanded &&
                (bodyLoading ? (
                    <div className="flex items-center gap-2 text-xs text-secondary">
                        <Spinner /> Loading the skill body
                    </div>
                ) : bodyFailed ? (
                    <div className="text-xs text-danger">
                        Couldn't load the skill body. <Link onClick={() => void fetchBody()}>Try again</Link>
                    </div>
                ) : body !== null ? (
                    <div className="max-h-60 overflow-y-auto rounded border border-primary bg-surface-primary p-3">
                        <LemonMarkdown className="text-xs" disableImages>
                            {body}
                        </LemonMarkdown>
                    </div>
                ) : null)}
        </div>
    )
}

/**
 * A searchable, grouped list of skills with per-row preview and select. Fully controlled: the
 * caller fetches and groups the skills, this component only renders and filters them, so it can
 * host any product's picking flow (its first consumer is ReviewHog's "Use an existing skill").
 */
export function SkillPicker({
    groups,
    loading = false,
    emptyMessage = 'No skills available',
    selectLabel = 'Select',
    onSelect,
    loadBody,
    'data-attr': dataAttr,
}: SkillPickerProps): JSX.Element {
    const [search, setSearch] = useState('')
    const query = search.trim().toLowerCase()

    const filteredGroups = groups
        .map((group) => ({ ...group, skills: group.skills.filter((skill) => matchesQuery(skill, query)) }))
        .filter((group) => group.skills.length > 0)
    const nothingToOffer = groups.every((group) => group.skills.length === 0)

    return (
        <div className="flex flex-col gap-3" data-attr={dataAttr}>
            <LemonInput
                type="search"
                fullWidth
                placeholder="Search skills"
                value={search}
                onChange={setSearch}
                autoFocus
                data-attr="skill-picker-search"
            />
            {loading ? (
                <div className="flex flex-col gap-2">
                    <LemonSkeleton className="h-16 w-full" />
                    <LemonSkeleton className="h-16 w-full" />
                    <LemonSkeleton className="h-16 w-full" />
                </div>
            ) : nothingToOffer ? (
                <p className="m-0 text-sm text-secondary">{emptyMessage}</p>
            ) : filteredGroups.length === 0 ? (
                <p className="m-0 text-sm text-secondary">No skills match your search.</p>
            ) : (
                <div className="flex max-h-120 flex-col gap-4 overflow-y-auto">
                    {filteredGroups.map((group) => (
                        <div key={group.key} className="flex flex-col gap-2">
                            <div className="flex items-center gap-2">
                                <span className="text-xxs font-semibold uppercase tracking-wide text-tertiary">
                                    {group.label}
                                </span>
                                <LemonTag type="muted" size="small">
                                    {group.skills.length}
                                </LemonTag>
                            </div>
                            {group.skills.map((skill) => (
                                <SkillPickerRow
                                    key={skill.name}
                                    skill={skill}
                                    selectLabel={selectLabel}
                                    onSelect={onSelect}
                                    loadBody={loadBody}
                                />
                            ))}
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}
