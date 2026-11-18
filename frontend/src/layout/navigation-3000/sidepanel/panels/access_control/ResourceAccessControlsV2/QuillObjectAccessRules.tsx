import type { ColumnDef } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import { Button, DataTable, Skeleton, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { toSentenceCase } from 'lib/utils/strings'

import { accessControlsLogic } from './accessControlsLogic'
import { AccessObjectRule, accessDetailLogic, objectRuleUrl } from './accessDetailLogic'
import { addObjectOverrideModalLogic } from './addObjectOverrideModalLogic'
import { objectRuleLevelOptions } from './helpers'
import type { ObjectAccessRulesProps } from './ObjectAccessRules'
import { QuillAccessDetailSection } from './QuillAccessDetailSection'
import { QuillAddObjectRuleModal } from './QuillAddObjectRuleModal'
import { QuillLevelSelect } from './QuillLevelSelect'
import { ScopeIcon } from './ScopeIcon'

const RULES_PER_PAGE = 20

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

    const columns: ColumnDef<AccessObjectRule>[] = [
        {
            id: 'object',
            header: 'Object',
            meta: { expand: true },
            enableSorting: false,
            cell: ({ row }) => {
                const href = objectRuleUrl(row.original)
                return (
                    <div className="flex min-w-0 items-center gap-2">
                        <Tooltip>
                            <TooltipTrigger
                                render={<span className="flex shrink-0 items-center text-muted-foreground" />}
                            >
                                <ScopeIcon scope={row.original.resource} />
                            </TooltipTrigger>
                            <TooltipContent>{toSentenceCase(row.original.resource.replace(/_/g, ' '))}</TooltipContent>
                        </Tooltip>
                        {href ? (
                            <Button
                                variant="link-foreground"
                                size="sm"
                                nativeButton={false}
                                render={<LinkPrimitive to={href} />}
                            >
                                {row.original.name}
                            </Button>
                        ) : (
                            <Text size="xs" weight="medium" render={<span className="truncate" />}>
                                {row.original.name}
                            </Text>
                        )}
                    </div>
                )
            },
        },
        {
            id: 'access',
            header: 'Access',
            meta: { align: 'right' },
            enableSorting: false,
            cell: ({ row }) => {
                const resourceLevels = objectRuleResourceOptions.find((r) => r.resource === row.original.resource)
                return (
                    <QuillLevelSelect
                        value={row.original.access_level}
                        options={objectRuleLevelOptions(
                            resourceLevels?.available_access_levels ?? availableResourceLevels,
                            resourceLevels?.minimum_access_level
                        )}
                        onChange={(level) => setObjectRule(row.original.resource, row.original.resource_id, level)}
                        disabledReason={editDisabledReason}
                    />
                )
            },
        },
        {
            id: 'actions',
            header: '',
            meta: { align: 'right' },
            enableSorting: false,
            cell: ({ row }) => (
                <Button
                    size="icon"
                    aria-label="Remove the rule"
                    tooltip="Remove the rule"
                    disabledReason={editDisabledReason}
                    onClick={() => setObjectRule(row.original.resource, row.original.resource_id, null)}
                >
                    <IconTrash />
                </Button>
            ),
        },
    ]

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
                <DataTable
                    columns={columns}
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
