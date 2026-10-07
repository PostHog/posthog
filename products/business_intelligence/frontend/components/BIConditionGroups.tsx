import { useState } from 'react'

import { LemonButton, LemonModal, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { BIConditionGroup } from '~/queries/schema/schema-business-intelligence'

import { moveBICondition, normalizeBIConditionGroup, updateBIConditionGroup } from '../biFilterGroups'

interface FilterOption {
    value: string
    label: string
}

function GroupEditor({
    root,
    group,
    path,
    options,
    onChange,
}: {
    root: BIConditionGroup
    group: BIConditionGroup
    path: number[]
    options: FilterOption[]
    onChange: (group: BIConditionGroup) => void
}): JSX.Element {
    const update = (change: (node: BIConditionGroup) => BIConditionGroup): void =>
        onChange(updateBIConditionGroup(root, path, change))
    return (
        <div
            className="flex min-w-0 flex-col gap-2 rounded border p-2"
            data-attr="bi-filter-group"
            data-depth={path.length}
        >
            <div className="flex flex-wrap items-center gap-2">
                <LemonSelect
                    size="small"
                    value={group.operator}
                    options={[
                        { value: 'AND', label: 'AND — match all' },
                        { value: 'OR', label: 'OR — match any' },
                    ]}
                    onChange={(operator) => update((node) => ({ ...node, operator }))}
                />
                {path.length > 0 && (
                    <LemonButton
                        size="xsmall"
                        onClick={() =>
                            onChange(
                                updateBIConditionGroup(root, path.slice(0, -1), (parent) => ({
                                    ...parent,
                                    groups: parent.groups.filter((_, index) => index !== path[path.length - 1]),
                                }))
                            )
                        }
                    >
                        Ungroup
                    </LemonButton>
                )}
            </div>
            {group.filters.map((id) => (
                <LemonTag key={id} className="max-w-full whitespace-normal">
                    {options.find((option) => option.value === id)?.label}
                </LemonTag>
            ))}
            {group.groups.map((child, index) => (
                <GroupEditor
                    key={index}
                    root={root}
                    group={child}
                    path={[...path, index]}
                    options={options}
                    onChange={onChange}
                />
            ))}
            <div className="flex flex-wrap gap-2">
                <LemonSelect
                    size="small"
                    placeholder="Move filter here"
                    value={null}
                    options={options.filter((option) => !group.filters.includes(option.value))}
                    onChange={(id) => id && onChange(moveBICondition(root, id, path))}
                />
                <LemonButton
                    size="xsmall"
                    disabledReason={path.length >= 8 ? 'Maximum group depth reached' : undefined}
                    onClick={() =>
                        update((node) => ({
                            ...node,
                            groups: [...node.groups, { operator: 'AND', filters: [], groups: [] }],
                        }))
                    }
                >
                    Add group
                </LemonButton>
            </div>
        </div>
    )
}

export function BIConditionGroups({
    title,
    group,
    options,
    onChange,
}: {
    title: string
    group: BIConditionGroup | undefined
    options: FilterOption[]
    onChange: (group: BIConditionGroup) => void
}): JSX.Element {
    const [open, setOpen] = useState(false)
    const normalized = normalizeBIConditionGroup(
        group,
        options.map((option) => option.value)
    )
    return (
        <>
            <LemonButton
                size="xsmall"
                disabledReason={!options.length ? 'Add filters first' : undefined}
                onClick={() => setOpen(true)}
            >
                AND / OR groups
            </LemonButton>
            <LemonModal
                title={title}
                isOpen={open}
                onClose={() => setOpen(false)}
                width={560}
                footer={
                    <LemonButton type="primary" onClick={() => setOpen(false)}>
                        Done
                    </LemonButton>
                }
            >
                <p className="text-secondary">
                    Add a group, then move filters into it. Empty groups have no effect. Ungroup moves its filters back
                    to the outer group.
                </p>
                <GroupEditor root={normalized} group={normalized} path={[]} options={options} onChange={onChange} />
            </LemonModal>
        </>
    )
}
