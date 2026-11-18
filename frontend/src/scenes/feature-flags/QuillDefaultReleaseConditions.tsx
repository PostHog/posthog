import { useId } from 'react'

import { Button, Field, FieldLabel, Switch, Text } from '@posthog/quill'

import { FeatureFlagFilters } from '~/types'

import { QuillFeatureFlagReleaseConditionsCollapsible } from './QuillFeatureFlagReleaseConditionsCollapsible'

export function QuillDefaultReleaseConditions({
    isEnabled,
    filtersForEditor,
    hasChanges,
    loading,
    restrictedReason,
    onToggleEnabled,
    onFiltersChange,
    onSave,
    onDiscard,
}: {
    isEnabled: boolean
    filtersForEditor: FeatureFlagFilters
    hasChanges: boolean
    loading: boolean
    restrictedReason: string | null
    onToggleEnabled: (enabled: boolean) => void
    onFiltersChange: (filters: FeatureFlagFilters) => void
    onSave: () => void
    onDiscard: () => void
}): JSX.Element {
    const switchId = useId()

    return (
        <div className="flex flex-col gap-4">
            <Field orientation="horizontal" className="w-fit">
                <Switch
                    id={switchId}
                    data-attr="default-release-conditions-switch"
                    checked={isEnabled}
                    onCheckedChange={onToggleEnabled}
                    disabled={loading}
                    disabledReason={restrictedReason}
                />
                <FieldLabel htmlFor={switchId}>Apply default release conditions to new flags</FieldLabel>
            </Field>

            {isEnabled && (
                <div className="flex flex-col gap-4 rounded-lg border border-border p-4">
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        These conditions will be pre-populated when creating any new feature flag. Users can still
                        modify them during flag creation.
                    </Text>

                    <QuillFeatureFlagReleaseConditionsCollapsible
                        id="default-release-conditions"
                        filters={filtersForEditor}
                        onChange={onFiltersChange}
                        isDisabled={!!restrictedReason}
                    />
                </div>
            )}

            {hasChanges && (
                <div className="flex flex-wrap gap-2">
                    <Button variant="primary" onClick={onSave} loading={loading} disabledReason={restrictedReason}>
                        Save changes
                    </Button>
                    <Button variant="outline" onClick={onDiscard} disabledReason={restrictedReason}>
                        Discard changes
                    </Button>
                </div>
            )}
        </div>
    )
}
