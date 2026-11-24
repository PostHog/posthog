import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { Button, Field, FieldDescription, FieldError, FieldLabel, Heading, Input, Text } from '@posthog/quill'

import { TagsCombobox } from 'lib/components/Scenes/TagsCombobox'
import { QuillSettingSwitch } from 'scenes/settings/components/QuillSettingSwitch'

import { organizationIPRestrictionsLogic } from './organizationIPRestrictionsLogic'

export function QuillOrganizationIPRestrictions({
    testIp,
    testResult,
    testResultMessage,
    testDisabledReason,
    onEntriesChange,
    onTestIpChange,
    onTest,
}: {
    testIp: string
    testResult: boolean | null
    testResultMessage: string
    testDisabledReason: string | null
    onEntriesChange: (entries: string[]) => void
    onTestIpChange: (value: string) => void
    onTest: () => void
}): JSX.Element {
    const {
        currentOrganizationLoading: saving,
        enabled,
        values,
        validationError,
        editDisabledReason,
        saveDisabledReason,
        toggleDisabledReason,
    } = useValues(organizationIPRestrictionsLogic)
    const { save, setEnabled } = useActions(organizationIPRestrictionsLogic)
    const testInputId = useId()

    return (
        <div className="flex flex-col items-start gap-4">
            <QuillSettingSwitch
                label="Enable IP restrictions"
                dataAttr="ip-restrictions-enabled-toggle"
                checked={enabled}
                onCheckedChange={setEnabled}
                disabled={saving}
                disabledReason={toggleDisabledReason}
            />
            <Field data-invalid={!!validationError || undefined}>
                <FieldLabel>Allowed IP addresses and CIDR blocks</FieldLabel>
                <TagsCombobox
                    value={values}
                    onChange={onEntriesChange}
                    customValueNoun="IP address"
                    dataAttr="ip-restrictions-input"
                    placeholder="203.0.113.4 or 10.0.0.0/8"
                    disabled={saving}
                    disabledReason={editDisabledReason}
                    className="w-full"
                />
                {validationError && <FieldError>{validationError}</FieldError>}
                {values.length === 0 && (
                    <FieldDescription>
                        With no IP restrictions, members of your organization can access PostHog from any IP address.
                    </FieldDescription>
                )}
            </Field>
            <Button
                variant="primary"
                onClick={save}
                loading={saving}
                disabledReason={saveDisabledReason}
                data-attr="ip-restrictions-save"
            >
                Save
            </Button>

            <div className="flex w-full flex-col gap-2">
                <Heading size="sm" render={<h3 className="m-0" />}>
                    Test an IP address
                </Heading>
                <div className="flex flex-wrap items-end gap-2">
                    <Field className="w-72 max-w-full">
                        <FieldLabel htmlFor={testInputId} className="sr-only">
                            IP address to test
                        </FieldLabel>
                        <Input
                            id={testInputId}
                            size="sm"
                            placeholder="203.0.113.4"
                            value={testIp}
                            onChange={(event) => onTestIpChange(event.target.value)}
                            data-attr="ip-restrictions-test-input"
                        />
                    </Field>
                    <Button
                        variant="outline"
                        onClick={onTest}
                        disabledReason={testDisabledReason}
                        data-attr="ip-restrictions-test"
                    >
                        Test
                    </Button>
                </div>
                {testResult !== null && (
                    <Text
                        size="xs"
                        variant={testResult ? 'default' : 'destructive'}
                        className={testResult ? 'text-success-foreground' : undefined}
                        render={<p className="m-0" />}
                    >
                        {testResultMessage}
                    </Text>
                )}
            </div>
        </div>
    )
}
