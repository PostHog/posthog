import { Form, Field as KeaField } from 'kea-forms'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldDescription,
    FieldError,
    FieldLabel,
    Input,
    Label,
    Text,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill'

import type { WorkloadJobSettingsApi, WorkloadProviderApi } from '~/generated/core/api.schemas'

import { WorkloadConditionRows } from './WorkloadConditionRows'
import { WorkloadProviderIcon } from './WorkloadProviderIcon'
import { WorkloadSetupSnippet } from './WorkloadSetupSnippet'
import { WorkloadSubjectFields } from './WorkloadSubjectFields'
import { workloadTrustPoliciesLogic } from './workloadTrustPoliciesLogic'

export function QuillWorkloadTrustPolicyModal({
    isOpen,
    isNew,
    onClose,
    setup,
    hasUnsavedInput,
    isSubmitting,
    onSubmit,
    providers,
    showConditions,
    scopeSearchTerm,
    onScopeSearchTermChange,
    scopeRows,
}: {
    isOpen: boolean
    isNew: boolean
    onClose: () => void
    /** Set once a new policy is saved, to show how to set up the job instead of the form. */
    setup: { provider: WorkloadProviderApi; jobSettings: WorkloadJobSettingsApi } | null
    hasUnsavedInput: boolean
    isSubmitting: boolean
    onSubmit: () => void
    providers: WorkloadProviderApi[]
    showConditions: boolean
    scopeSearchTerm: string
    onScopeSearchTermChange: (searchTerm: string) => void
    scopeRows: JSX.Element[]
}): JSX.Element {
    return (
        <Dialog
            open={isOpen}
            onOpenChange={(open, details) => {
                // A stray click outside must not throw away a half-filled policy.
                if (!open && !(hasUnsavedInput && details.reason === 'outside-press')) {
                    onClose()
                }
            }}
        >
            <DialogContent className="sm:max-w-160">
                {setup ? (
                    <>
                        <DialogHeader>
                            <DialogTitle>Set up the workload</DialogTitle>
                        </DialogHeader>
                        <DialogBody>
                            <WorkloadSetupSnippet provider={setup.provider} jobSettings={setup.jobSettings} />
                        </DialogBody>
                        <DialogFooter>
                            <Button variant="primary" onClick={onClose} data-attr="workload-trust-policy-setup-done">
                                Done
                            </Button>
                        </DialogFooter>
                    </>
                ) : (
                    <>
                        <DialogHeader>
                            <DialogTitle>{isNew ? 'Add trusted workload' : 'Edit trusted workload'}</DialogTitle>
                        </DialogHeader>
                        <DialogBody>
                            <Form
                                logic={workloadTrustPoliciesLogic}
                                formKey="editingPolicy"
                                className="flex flex-col gap-4"
                            >
                                <KeaField name="issuer" noStyle>
                                    {({ value, onChange, error }) => (
                                        <Field data-invalid={error ? true : undefined}>
                                            <Label>Provider</Label>
                                            <ToggleGroup
                                                variant="outline"
                                                aria-label="Provider"
                                                className="w-full flex-wrap"
                                                value={value ? [value] : []}
                                                onValueChange={(next: string[]) => {
                                                    if (next[0]) {
                                                        onChange(next[0])
                                                    }
                                                }}
                                            >
                                                {providers.map((provider) => (
                                                    <ToggleGroupItem
                                                        key={provider.issuer}
                                                        value={provider.issuer}
                                                        className="flex-1"
                                                        data-attr={`workload-trust-policy-provider-${provider.key}`}
                                                    >
                                                        <WorkloadProviderIcon providerKey={provider.key} />
                                                        {provider.name}
                                                    </ToggleGroupItem>
                                                ))}
                                            </ToggleGroup>
                                            {error && <FieldError>{error}</FieldError>}
                                        </Field>
                                    )}
                                </KeaField>
                                <WorkloadSubjectFields />
                                {showConditions ? (
                                    <KeaField name="conditions" noStyle>
                                        {({ error }) => (
                                            <Field data-invalid={error ? true : undefined}>
                                                <Label>Which runs can get a token</Label>
                                                <FieldDescription>
                                                    A token matches only when it meets every condition.
                                                </FieldDescription>
                                                <WorkloadConditionRows />
                                                {error && <FieldError>{error}</FieldError>}
                                            </Field>
                                        )}
                                    </KeaField>
                                ) : null}
                                <KeaField name="name" noStyle>
                                    {({ id, value, onChange, error }) => (
                                        <Field data-invalid={error ? true : undefined}>
                                            <FieldLabel htmlFor={id}>Name</FieldLabel>
                                            <Input
                                                id={id}
                                                value={value ?? ''}
                                                onChange={(event) => onChange(event.target.value)}
                                                placeholder="Production deploys"
                                                maxLength={200}
                                            />
                                            {error && <FieldError>{error}</FieldError>}
                                        </Field>
                                    )}
                                </KeaField>
                                <KeaField name="scopes" noStyle>
                                    {({ error }) => (
                                        <Field data-invalid={error ? true : undefined}>
                                            <Label>Scopes</Label>
                                            <FieldDescription>
                                                Every token from this policy gets these scopes. Scopes that would let a
                                                token outlive itself aren't available.
                                            </FieldDescription>
                                            <Input
                                                type="search"
                                                placeholder="Search scopes"
                                                aria-label="Search scopes"
                                                value={scopeSearchTerm}
                                                onChange={(event) => onScopeSearchTermChange(event.target.value)}
                                            />
                                            <div className="flex flex-col gap-2">
                                                {scopeRows.length === 0 ? (
                                                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                                        No scopes match your search.
                                                    </Text>
                                                ) : (
                                                    scopeRows
                                                )}
                                            </div>
                                            {error && <FieldError>{error}</FieldError>}
                                        </Field>
                                    )}
                                </KeaField>
                            </Form>
                        </DialogBody>
                        <DialogFooter>
                            <Button variant="outline" onClick={onClose}>
                                Cancel
                            </Button>
                            <Button
                                variant="primary"
                                loading={isSubmitting}
                                disabledReason={!hasUnsavedInput ? 'No changes to save' : undefined}
                                onClick={onSubmit}
                                data-attr="workload-trust-policy-save"
                            >
                                {isNew ? 'Add trusted workload' : 'Save'}
                            </Button>
                        </DialogFooter>
                    </>
                )}
            </DialogContent>
        </Dialog>
    )
}
