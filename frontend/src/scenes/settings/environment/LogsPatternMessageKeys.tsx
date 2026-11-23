import { useActions, useValues } from 'kea'
import { Field as KeaField, Form } from 'kea-forms'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'
import {
    Button,
    Field,
    FieldDescription,
    FieldError,
    FieldLabel,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    Skeleton,
} from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { logsConfigLogic } from 'products/logs/frontend/logsConfigLogic'

import { QuillSortableChipInput } from './QuillSortableChipInput'

export function LogsPatternMessageKeys(): JSX.Element {
    const {
        logsConfig,
        logsConfigLoading,
        patternMessageKeysChanged,
        patternMessageKeysValidationErrors,
        isPatternMessageKeysSubmitting,
    } = useValues(logsConfigLogic)
    const { loadLogsConfig } = useActions(logsConfigLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!logsConfig && todayRailNav) {
        return logsConfigLoading ? (
            <Skeleton className="h-8 max-w-md" />
        ) : (
            <Item tone="destructive" size="sm">
                <ItemContent>
                    <ItemDescription>Could not load pattern message extraction settings.</ItemDescription>
                </ItemContent>
                <ItemActions>
                    <Button variant="outline" onClick={() => loadLogsConfig()}>
                        Retry
                    </Button>
                </ItemActions>
            </Item>
        )
    }

    if (!logsConfig) {
        return logsConfigLoading ? (
            <LemonSkeleton className="w-1/2 h-4" />
        ) : (
            <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadLogsConfig() }}>
                Could not load pattern message extraction settings.
            </LemonBanner>
        )
    }

    const keysError = patternMessageKeysValidationErrors.keys?.[0]
    const saveDisabledReason =
        restrictedReason || keysError || (!patternMessageKeysChanged ? 'No changes to save' : undefined)

    if (todayRailNav) {
        return (
            <Form
                logic={logsConfigLogic}
                formKey="patternMessageKeys"
                enableFormOnSubmit
                className="flex flex-col items-start gap-2"
            >
                <KeaField name="keys" noStyle>
                    {({ id, value, onChange }) => (
                        <Field data-invalid={keysError ? true : undefined} className="w-full max-w-md">
                            <FieldLabel htmlFor={id}>Message keys</FieldLabel>
                            <QuillSortableChipInput
                                id={id}
                                value={value}
                                onChange={onChange}
                                limit={10}
                                placeholder="Add a message key"
                                disabledReason={
                                    restrictedReason ||
                                    (logsConfigLoading || isPatternMessageKeysSubmitting ? 'Updating settings' : null)
                                }
                                dataAttr="logs-pattern-message-keys-select"
                            />
                            <FieldDescription>
                                Drag keys to change their priority. Clear all keys to disable message extraction.
                            </FieldDescription>
                            {keysError && <FieldError>{keysError}</FieldError>}
                        </Field>
                    )}
                </KeaField>
                <Button
                    type="submit"
                    variant="primary"
                    disabledReason={saveDisabledReason}
                    loading={logsConfigLoading || isPatternMessageKeysSubmitting}
                >
                    Save
                </Button>
            </Form>
        )
    }

    return (
        <Form logic={logsConfigLogic} formKey="patternMessageKeys" enableFormOnSubmit className="space-y-4">
            <LemonField
                name="keys"
                label="Message keys"
                help="Drag keys to change their priority. Clear all keys to disable message extraction."
            >
                <LemonInputSelect
                    mode="multiple"
                    allowCustomValues
                    sortable={!restrictedReason && !logsConfigLoading && !isPatternMessageKeysSubmitting}
                    limit={10}
                    disableCommaSplitting
                    bulkActions="clear-all"
                    placeholder="Add a message key"
                    loading={logsConfigLoading}
                    disabled={logsConfigLoading || isPatternMessageKeysSubmitting || !!restrictedReason}
                    data-attr="logs-pattern-message-keys-select"
                    className="max-w-md"
                />
            </LemonField>
            {keysError && <LemonField.Error error={keysError} />}
            <LemonButton
                type="primary"
                htmlType="submit"
                disabledReason={saveDisabledReason}
                loading={logsConfigLoading || isPatternMessageKeysSubmitting}
            >
                Save
            </LemonButton>
        </Form>
    )
}
