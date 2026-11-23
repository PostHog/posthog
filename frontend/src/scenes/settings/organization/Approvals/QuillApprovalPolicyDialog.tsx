import { useId } from 'react'

import { IconInfo } from '@posthog/icons'
import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Empty,
    EmptyDescription,
    EmptyHeader,
    Field,
    FieldDescription,
    FieldGroup,
    FieldLabel,
    FieldLegend,
    FieldSeparator,
    FieldSet,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Switch,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { ApprovalActionKey } from 'scenes/approvals/utils'

import { CONDITION_TYPES_TOOLTIP, ConditionRule, GATEABLE_FIELDS } from './approvalPolicyConditions'
import { QuillApprovalPolicyMultiSelect, QuillApprovalPolicyOption } from './QuillApprovalPolicyMultiSelect'
import { QuillApprovalPolicyRuleRow } from './QuillApprovalPolicyRuleRow'

const QUORUM_OPTIONS = [
    { label: '1 approval', value: 1 },
    { label: '2 approvals', value: 2 },
    { label: '3 approvals', value: 3 },
]

function HelpButton({ label, help }: { label: string; help: string }): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger delay={0} render={<Button size="icon-xs" aria-label={`About ${label.toLowerCase()}`} />}>
                <IconInfo />
            </TooltipTrigger>
            <TooltipContent className="max-w-80 whitespace-pre-line">{help}</TooltipContent>
        </Tooltip>
    )
}

export function QuillApprovalPolicyDialog({
    isEditing,
    actionKey,
    actionOptions,
    supportsConditions,
    rules,
    availableFields,
    quorum,
    allowSelfApprove,
    approverUserIds,
    approverRoleIds,
    bypassAdminsOwners,
    bypassRoleIds,
    userOptions,
    roleOptions,
    onActionKeyChange,
    onAddRule,
    onUpdateRule,
    onRemoveRule,
    onQuorumChange,
    onAllowSelfApproveChange,
    onApproverUserIdsChange,
    onApproverRoleIdsChange,
    onBypassAdminsOwnersChange,
    onBypassRoleIdsChange,
    onSave,
    onClose,
}: {
    isEditing: boolean
    actionKey: string
    actionOptions: { label: string; value: string }[]
    supportsConditions: boolean
    rules: ConditionRule[]
    availableFields: [string, (typeof GATEABLE_FIELDS)[string]][]
    quorum: number
    allowSelfApprove: boolean
    approverUserIds: number[]
    approverRoleIds: string[]
    bypassAdminsOwners: boolean
    bypassRoleIds: string[]
    userOptions: QuillApprovalPolicyOption[]
    roleOptions: QuillApprovalPolicyOption[]
    onActionKeyChange: (value: string) => void
    onAddRule: (field: string) => void
    onUpdateRule: (index: number, updates: Partial<ConditionRule>) => void
    onRemoveRule: (index: number) => void
    onQuorumChange: (quorum: number) => void
    onAllowSelfApproveChange: (allow: boolean) => void
    onApproverUserIdsChange: (ids: number[]) => void
    onApproverRoleIdsChange: (ids: string[]) => void
    onBypassAdminsOwnersChange: (bypass: boolean) => void
    onBypassRoleIdsChange: (ids: string[]) => void
    onSave: () => void
    onClose: () => void
}): JSX.Element {
    const idPrefix = useId()
    const ids = {
        actionKey: `${idPrefix}-action-key`,
        approverUsers: `${idPrefix}-approver-users`,
        approverRoles: `${idPrefix}-approver-roles`,
        quorum: `${idPrefix}-quorum`,
        selfApprove: `${idPrefix}-self-approve`,
        bypassAdmins: `${idPrefix}-bypass-admins`,
        bypassRoles: `${idPrefix}-bypass-roles`,
    }
    const addFieldOptions = availableFields.map(([key, config]) => ({ value: key, label: config.label }))

    return (
        <Dialog
            open
            onOpenChange={(open) => {
                if (!open) {
                    onClose()
                }
            }}
        >
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>{isEditing ? 'Edit approval policy' : 'Create approval policy'}</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <FieldGroup>
                        <Field>
                            <FieldLabel htmlFor={ids.actionKey}>Action type</FieldLabel>
                            <Select<string>
                                items={actionOptions}
                                value={actionKey}
                                onValueChange={(value) => value && onActionKeyChange(value)}
                            >
                                <SelectTrigger id={ids.actionKey} className="w-full">
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    {actionOptions.map((option) => (
                                        <SelectItem key={option.value} value={option.value}>
                                            {option.label}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </Field>

                        {supportsConditions && (
                            <Field>
                                <div className="flex items-center gap-1">
                                    <Text size="xs" weight="medium" render={<span />}>
                                        Require approval when
                                    </Text>
                                    <HelpButton label="Require approval when" help={CONDITION_TYPES_TOOLTIP} />
                                </div>

                                {rules.length === 0 ? (
                                    <Empty className="border border-dashed">
                                        <EmptyHeader>
                                            <EmptyDescription>
                                                No conditions configured. Add a field to require approval for specific
                                                changes.
                                            </EmptyDescription>
                                        </EmptyHeader>
                                    </Empty>
                                ) : (
                                    <div className="flex flex-col gap-2">
                                        {rules.map((rule, index) => (
                                            <QuillApprovalPolicyRuleRow
                                                key={rule.field}
                                                rule={rule}
                                                onChange={(updates) => onUpdateRule(index, updates)}
                                                onRemove={() => onRemoveRule(index)}
                                            />
                                        ))}
                                    </div>
                                )}

                                {addFieldOptions.length > 0 && (
                                    <div>
                                        <Select<string | null>
                                            items={addFieldOptions}
                                            value={null}
                                            onValueChange={(value) => value && onAddRule(value)}
                                        >
                                            <SelectTrigger aria-label="Add field">
                                                <SelectValue placeholder="+ Add field" />
                                            </SelectTrigger>
                                            <SelectContent>
                                                {addFieldOptions.map((option) => (
                                                    <SelectItem key={option.value} value={option.value}>
                                                        {option.label}
                                                    </SelectItem>
                                                ))}
                                            </SelectContent>
                                        </Select>
                                    </div>
                                )}

                                <FieldDescription>
                                    {actionKey === ApprovalActionKey.EXPERIMENT_UPDATE
                                        ? "With no conditions, any change to an experiment's rollout, variant split or holdout exclusion needs approval. Changes to its release conditions do not."
                                        : "With no conditions, any change to a flag's rollout needs approval. So does any change to its release conditions, unless an experiment, survey, product tour or early access feature manages the flag."}
                                </FieldDescription>
                            </Field>
                        )}

                        <Field>
                            <FieldLabel htmlFor={ids.approverUsers}>Approver users</FieldLabel>
                            <QuillApprovalPolicyMultiSelect
                                id={ids.approverUsers}
                                options={userOptions}
                                value={approverUserIds.map(String)}
                                onChange={(values) => onApproverUserIdsChange(values.map(Number))}
                                placeholder="Select users who can approve"
                            />
                            <FieldDescription>Users who can approve change requests for this action</FieldDescription>
                        </Field>

                        <Field>
                            <FieldLabel htmlFor={ids.approverRoles}>Approver roles</FieldLabel>
                            <QuillApprovalPolicyMultiSelect
                                id={ids.approverRoles}
                                options={roleOptions}
                                value={approverRoleIds}
                                onChange={onApproverRoleIdsChange}
                                placeholder="Select roles who can approve"
                            />
                            <FieldDescription>
                                Users with any of these roles can approve change requests for this action
                            </FieldDescription>
                        </Field>

                        <Field>
                            <FieldLabel htmlFor={ids.quorum}>Approvals required</FieldLabel>
                            <Select<number>
                                items={QUORUM_OPTIONS}
                                value={quorum}
                                onValueChange={(value) => value && onQuorumChange(value)}
                            >
                                <SelectTrigger id={ids.quorum} className="w-full">
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    {QUORUM_OPTIONS.map((option) => (
                                        <SelectItem key={option.value} value={option.value}>
                                            {option.label}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </Field>

                        <Field orientation="horizontal" className="w-fit">
                            <Switch
                                id={ids.selfApprove}
                                checked={allowSelfApprove}
                                onCheckedChange={(checked) => onAllowSelfApproveChange(checked)}
                            />
                            <FieldLabel htmlFor={ids.selfApprove}>Allow self-approval</FieldLabel>
                            <HelpButton
                                label="Allow self-approval"
                                help="If enabled, the person requesting the change can also approve it. They still need to be in the approver list."
                            />
                        </Field>

                        <FieldSeparator />

                        <FieldSet>
                            <FieldLegend variant="label">Bypass options</FieldLegend>
                            <FieldDescription>
                                Users matching these criteria can skip the approval flow entirely
                            </FieldDescription>
                            <FieldGroup>
                                <Field orientation="horizontal" className="w-fit">
                                    <Switch
                                        id={ids.bypassAdmins}
                                        checked={bypassAdminsOwners}
                                        onCheckedChange={(checked) => onBypassAdminsOwnersChange(checked)}
                                    />
                                    <FieldLabel htmlFor={ids.bypassAdmins}>
                                        Allow org admins and owners to bypass
                                    </FieldLabel>
                                    <HelpButton
                                        label="Allow org admins and owners to bypass"
                                        help="Organization admins and owners can perform this action without requiring approval"
                                    />
                                </Field>
                                <Field>
                                    <FieldLabel htmlFor={ids.bypassRoles}>Bypass roles</FieldLabel>
                                    <QuillApprovalPolicyMultiSelect
                                        id={ids.bypassRoles}
                                        options={roleOptions}
                                        value={bypassRoleIds}
                                        onChange={onBypassRoleIdsChange}
                                        placeholder="Select roles that can bypass approval"
                                    />
                                    <FieldDescription>
                                        Users with any of these roles can skip the approval flow
                                    </FieldDescription>
                                </Field>
                            </FieldGroup>
                        </FieldSet>
                    </FieldGroup>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={onClose}>
                        Cancel
                    </Button>
                    <Button variant="primary" onClick={onSave}>
                        Save
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
