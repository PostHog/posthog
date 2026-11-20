import type { CellContext, ColumnDef } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'
import { createContext, useContext } from 'react'

import { IconPlus, IconTrash } from '@posthog/icons'
import { Button, DataTable, Skeleton, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { toSentenceCase } from 'lib/utils/strings'

import { AccessControlLevel } from '~/types'

import { accessControlsLogic } from './accessControlsLogic'
import { AccessObjectRule, accessDetailLogic, objectRuleUrl } from './accessDetailLogic'
import { addObjectOverrideModalLogic } from './addObjectOverrideModalLogic'
import { objectRuleLevelOptions } from './helpers'
import type { ObjectAccessRulesProps } from './ObjectAccessRules'
import { QuillAccessDetailSection } from './QuillAccessDetailSection'
import { QuillAddObjectRuleModal } from './QuillAddObjectRuleModal'
import { QuillLevelSelect, type QuillLevelSelectOption } from './QuillLevelSelect'
import { ScopeIcon } from './ScopeIcon'

const RULES_PER_PAGE = 20

interface ObjectRuleRowEditing {
    editDisabledReason: string | undefined
    levelOptionsFor: (rule: AccessObjectRule) => QuillLevelSelectOption<AccessControlLevel>[]
    onSetLevel: (rule: AccessObjectRule, level: AccessControlLevel | null) => void
}

// DataTable renders each cell function as a component, so the cells live at module scope and read the edit state
// from context. Rebuilding them when a save starts would remount the access select and drop keyboard focus.
const ObjectRuleRowEditingContext = createContext<ObjectRuleRowEditing | null>(null)

function useObjectRuleRowEditing(): ObjectRuleRowEditing {
    const rowEditing = useContext(ObjectRuleRowEditingContext)
    if (!rowEditing) {
        throw new Error('Object rule cells must render inside ObjectRuleRowEditingContext')
    }
    return rowEditing
}

function ObjectCell({ row }: CellContext<AccessObjectRule, unknown>): JSX.Element {
    const href = objectRuleUrl(row.original)
    return (
        <div className="flex min-w-0 items-center gap-2">
            <Tooltip>
                <TooltipTrigger render={<span className="flex shrink-0 items-center text-muted-foreground" />}>
                    <ScopeIcon scope={row.original.resource} />
                </TooltipTrigger>
                <TooltipContent>{toSentenceCase(row.original.resource.replace(/_/g, ' '))}</TooltipContent>
            </Tooltip>
            {href ? (
                <Button variant="link-foreground" size="sm" nativeButton={false} render={<LinkPrimitive to={href} />}>
                    {row.original.name}
                </Button>
            ) : (
                <Text size="xs" weight="medium" render={<span className="truncate" />}>
                    {row.original.name}
                </Text>
            )}
        </div>
    )
}

function AccessCell({ row }: CellContext<AccessObjectRule, unknown>): JSX.Element {
    const { editDisabledReason, levelOptionsFor, onSetLevel } = useObjectRuleRowEditing()

    return (
        <QuillLevelSelect
            value={row.original.access_level}
            options={levelOptionsFor(row.original)}
            onChange={(level) => onSetLevel(row.original, level)}
            disabledReason={editDisabledReason}
            aria-label={`Access to ${row.original.name}`}
        />
    )
}

function RemoveCell({ row }: CellContext<AccessObjectRule, unknown>): JSX.Element {
    const { editDisabledReason, onSetLevel } = useObjectRuleRowEditing()

    return (
        <Button
            size="icon"
            aria-label="Remove the rule"
            tooltip="Remove the rule"
            disabledReason={editDisabledReason}
            onClick={() => onSetLevel(row.original, null)}
        >
            <IconTrash />
        </Button>
    )
}

const COLUMNS: ColumnDef<AccessObjectRule>[] = [
    { id: 'object', header: 'Object', meta: { expand: true }, enableSorting: false, cell: ObjectCell },
    { id: 'access', header: 'Access', meta: { align: 'right' }, enableSorting: false, cell: AccessCell },
    { id: 'actions', header: '', meta: { align: 'right' }, enableSorting: false, cell: RemoveCell },
]

export function QuillObjectAccessRules({
    projectId,
    scopeType,
    subjectId,
    subjectNoun,
    canEdit,
    cannotEditReason,
}: ObjectAccessRulesProps): JSX.Element {
    const { objects, objectsLoading, ruleSaving } = useValues(accessDetailLogic({ projectId, scopeType, subjectId }))
    const { objectRuleResourceOptions, availableResourceLevels } = useValues(accessControlsLogic({ projectId }))
    const { setObjectRule } = useActions(accessDetailLogic({ projectId, scopeType, subjectId }))
    const { openModal } = useActions(addObjectOverrideModalLogic({ projectId, scopeType, subjectId }))

    const editDisabledReason = !canEdit
        ? (cannotEditReason ?? 'You cannot edit this')
        : ruleSaving
          ? 'Saving…'
          : undefined

    const levelOptionsFor = (rule: AccessObjectRule): QuillLevelSelectOption<AccessControlLevel>[] => {
        const resourceLevels = objectRuleResourceOptions.find((r) => r.resource === rule.resource)
        return objectRuleLevelOptions(
            resourceLevels?.available_access_levels ?? availableResourceLevels,
            resourceLevels?.minimum_access_level
        )
    }
    const rowEditing: ObjectRuleRowEditing = {
        editDisabledReason,
        levelOptionsFor,
        onSetLevel: (rule, level) => setObjectRule(rule.resource, rule.resource_id, level),
    }

    return (
        <QuillAccessDetailSection
            title="One-off access overrides"
            description={
                scopeType === 'default'
                    ? 'Specific dashboards, insights, notebooks and warehouse tables everyone is given access to, or blocked from, regardless of the defaults above.'
                    : `Specific dashboards, insights, notebooks and warehouse tables this ${subjectNoun} is given access to, or blocked from, regardless of the products above.`
            }
        >
            <QuillAddObjectRuleModal projectId={projectId} scopeType={scopeType} subjectId={subjectId} />
            {objectsLoading && objects.length === 0 ? (
                <Skeleton className="h-24 w-full" />
            ) : (
                <ObjectRuleRowEditingContext.Provider value={rowEditing}>
                    <DataTable
                        columns={COLUMNS}
                        data={objects}
                        getRowId={(rule) => `${rule.resource}:${rule.resource_id}`}
                        fullWidth
                        pageSize={objects.length > RULES_PER_PAGE ? RULES_PER_PAGE : undefined}
                        empty={
                            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                {`No one-off access overrides for this ${subjectNoun}.`}
                            </Text>
                        }
                    />
                </ObjectRuleRowEditingContext.Provider>
            )}
            <div className="flex">
                <Button variant="outline" onClick={openModal} disabledReason={editDisabledReason}>
                    <IconPlus />
                    Add rule
                </Button>
            </div>
        </QuillAccessDetailSection>
    )
}
