import { useActions, useValues } from 'kea'
import { Field as KeaField, Form } from 'kea-forms'

import { IconPlus, IconSearch } from '@posthog/icons'
import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Input,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Text,
    Textarea,
} from '@posthog/quill'

import { ScopeAccessGroup } from 'lib/components/ScopeAccessRow/ScopeAccessGroup'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { API_KEY_SCOPE_PRESETS } from 'lib/scopes'
import { QuillSettingFormField } from 'scenes/settings/components/QuillSettingFormField'

import { personalAPIKeysLogic } from './personalAPIKeysLogic'
import { editingKeySubmitDisabledReason, openUpgradeHashingRollDialog } from './personalAPIKeysUtils'
import { QuillKeyExpirationField } from './QuillKeyExpirationField'
import { QuillUserDefinedAccessSelector } from './scopes/ScopeAccessSelector/QuillUserDefinedAccessSelector'

export function QuillEditKeyModal(): JSX.Element {
    const {
        editingKeyId,
        isEditingKeySubmitting,
        editingKeyChanged,
        allAccessSelected,
        isEditingKeyLegacy,
        editingKey,
        allTeams,
        allOrganizations,
        filteredScopeGroups,
        searchTerm,
        isDescriptionFieldVisible,
        keys,
    } = useValues(personalAPIKeysLogic)
    const {
        setEditingKeyId,
        setScopeRadioValue,
        setScopeGroupAccess,
        submitEditingKey,
        resetScopes,
        setSearchTerm,
        rollKey,
        showDescriptionField,
    } = useActions(personalAPIKeysLogic)
    const { isCloudOrDev } = useValues(preflightLogic)

    const isNew = editingKeyId === 'new'
    const editingKeyRecord = isNew ? undefined : keys.find((key) => key.id === editingKeyId)
    const submitDisabledReason = editingKeySubmitDisabledReason(editingKeyChanged, editingKey)
    const presets = API_KEY_SCOPE_PRESETS.filter((preset) => !preset.isCloudOnly || isCloudOrDev)

    return (
        <Form logic={personalAPIKeysLogic} formKey="editingKey">
            <Dialog
                open={!!editingKeyId}
                onOpenChange={(open: boolean) => {
                    if (!open) {
                        setEditingKeyId(null)
                    }
                }}
                disablePointerDismissal={editingKeyChanged}
            >
                <DialogContent className="sm:max-w-160">
                    <DialogHeader>
                        <DialogTitle>{`${isNew ? 'Create' : 'Edit'} personal API key`}</DialogTitle>
                    </DialogHeader>
                    <DialogBody>
                        <div className="flex flex-col gap-4">
                            {!isNew && isEditingKeyLegacy && (
                                <Item tone="warning" size="sm">
                                    <ItemContent>
                                        <ItemDescription>
                                            <b>This key uses legacy hashing.</b> Roll it to upgrade to the new secure
                                            format. Your existing key value will become invalid.
                                        </ItemDescription>
                                    </ItemContent>
                                    <ItemActions>
                                        <Button
                                            variant="outline"
                                            onClick={() => {
                                                if (editingKeyRecord) {
                                                    openUpgradeHashingRollDialog(
                                                        editingKeyRecord,
                                                        () => setEditingKeyId(null),
                                                        rollKey
                                                    )
                                                }
                                            }}
                                        >
                                            Roll key
                                        </Button>
                                    </ItemActions>
                                </Item>
                            )}
                            <div className="flex flex-col gap-2">
                                <QuillSettingFormField name="label" label="Label">
                                    {({ id, value, onChange }) => (
                                        <Input
                                            id={id}
                                            value={value ?? ''}
                                            onChange={(event) => onChange(event.target.value)}
                                            placeholder='For example "Reports bot" or "Zapier"'
                                            maxLength={40}
                                        />
                                    )}
                                </QuillSettingFormField>
                                {isDescriptionFieldVisible ? (
                                    <QuillSettingFormField
                                        name="description"
                                        label={
                                            <>
                                                Description
                                                <Text size="xs" variant="muted" render={<span />}>
                                                    (optional)
                                                </Text>
                                            </>
                                        }
                                    >
                                        {({ id, value, onChange }) => (
                                            <Textarea
                                                id={id}
                                                value={value ?? ''}
                                                onChange={(event) => onChange(event.target.value)}
                                                placeholder="What is this key used for, and where? For example a link to the integration using it"
                                                maxLength={1000}
                                                rows={2}
                                                data-attr="personal-api-key-description"
                                            />
                                        )}
                                    </QuillSettingFormField>
                                ) : (
                                    <div>
                                        <Button
                                            onClick={() => showDescriptionField()}
                                            data-attr="personal-api-key-add-description"
                                        >
                                            <IconPlus />
                                            Add description
                                        </Button>
                                    </div>
                                )}
                            </div>
                            <QuillKeyExpirationField currentExpiresAt={editingKeyRecord?.expires_at ?? null} />
                            <QuillUserDefinedAccessSelector
                                accessType={editingKey.access_type}
                                organizations={allOrganizations}
                                teams={allTeams ?? undefined}
                            />
                            <div className="flex flex-col gap-2">
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                    <Text size="xs" weight="medium" render={<span />} className="m-0">
                                        Scopes
                                    </Text>
                                    <KeaField name="preset" noStyle>
                                        {({ value, onChange }) => (
                                            <Select
                                                value={value ?? null}
                                                onValueChange={(next) => next && onChange(next)}
                                            >
                                                <SelectTrigger aria-label="Scope preset">
                                                    <SelectValue>
                                                        {(selected: string | null) =>
                                                            presets.find((preset) => preset.value === selected)
                                                                ?.label ?? 'Select preset'
                                                        }
                                                    </SelectValue>
                                                </SelectTrigger>
                                                <SelectContent align="end">
                                                    {presets.map((preset) => (
                                                        <SelectItem key={preset.value} value={preset.value}>
                                                            {preset.label}
                                                        </SelectItem>
                                                    ))}
                                                </SelectContent>
                                            </Select>
                                        )}
                                    </KeaField>
                                </div>
                                <KeaField name="scopes" noStyle>
                                    {() => (
                                        <div className="flex flex-col gap-2">
                                            <Text size="xs" render={<p className="m-0" />}>
                                                Personal API keys are scoped to limit what actions they are able to do.
                                                We highly recommend you only give the key the permissions it needs to do
                                                its job. You can add or revoke scopes later.
                                            </Text>
                                            <Text size="xs" render={<p className="m-0" />}>
                                                Your personal API key can never take actions for which your account is
                                                missing permissions.
                                            </Text>
                                            {allAccessSelected ? (
                                                <Item tone="warning" size="sm">
                                                    <ItemContent>
                                                        <ItemDescription>
                                                            <b>
                                                                This personal API key has full access to all supported
                                                                endpoints!
                                                            </b>{' '}
                                                            We highly recommend scoping this to only what it needs.
                                                        </ItemDescription>
                                                    </ItemContent>
                                                    <ItemActions>
                                                        <Button variant="outline" onClick={() => resetScopes()}>
                                                            Reset
                                                        </Button>
                                                    </ItemActions>
                                                </Item>
                                            ) : (
                                                <div className="flex flex-col gap-2">
                                                    <InputGroup size="sm">
                                                        <InputGroupAddon align="inline-start">
                                                            <IconSearch />
                                                        </InputGroupAddon>
                                                        <InputGroupInput
                                                            type="search"
                                                            placeholder="Search scopes..."
                                                            aria-label="Search scopes"
                                                            value={searchTerm}
                                                            onChange={(event) => setSearchTerm(event.target.value)}
                                                        />
                                                    </InputGroup>
                                                    {filteredScopeGroups.length === 0 ? (
                                                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                                            No scopes match "{searchTerm}"
                                                        </Text>
                                                    ) : (
                                                        <div>
                                                            {filteredScopeGroups.map((group) => (
                                                                <ScopeAccessGroup
                                                                    // A search opens every group, and clearing it closes them again.
                                                                    key={`${group.label}-${searchTerm !== ''}`}
                                                                    group={group}
                                                                    defaultOpen={searchTerm !== ''}
                                                                    onChangeRow={setScopeRadioValue}
                                                                    onChangeGroup={setScopeGroupAccess}
                                                                    dataAttrPrefix="personal-api-key-scope-group"
                                                                />
                                                            ))}
                                                        </div>
                                                    )}
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </KeaField>
                            </div>
                        </div>
                    </DialogBody>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setEditingKeyId(null)}>
                            Cancel
                        </Button>
                        <Button
                            variant="primary"
                            loading={isEditingKeySubmitting}
                            disabledReason={submitDisabledReason}
                            onClick={() => submitEditingKey()}
                        >
                            {isNew ? 'Create key' : 'Save key'}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </Form>
    )
}
