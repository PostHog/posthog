import { useValues } from 'kea'

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { QuillSettingFormField } from 'scenes/settings/components/QuillSettingFormField'

import { KeyExpirationOption, expiresAtForOption, personalAPIKeysLogic } from './personalAPIKeysLogic'
import { EXPIRY_DATE_FORMAT, EXPIRY_TIME_FORMAT, keyExpirationOptions } from './personalAPIKeysUtils'

export function QuillKeyExpirationField({ currentExpiresAt }: { currentExpiresAt: string | null }): JSX.Element {
    const { editingKey } = useValues(personalAPIKeysLogic)

    const options = keyExpirationOptions(currentExpiresAt)
    const expiresAt = expiresAtForOption(editingKey.expiration)

    return (
        <div className="flex flex-col gap-1">
            <QuillSettingFormField name="expiration" label="Expiration">
                {({ id, value, onChange }) => (
                    <Select<KeyExpirationOption> value={value ?? null} onValueChange={(next) => next && onChange(next)}>
                        <SelectTrigger id={id} data-attr="personal-api-key-expiration" className="w-full">
                            <SelectValue>
                                {(selected: KeyExpirationOption) =>
                                    options.find((option) => 'value' in option && option.value === selected)?.label
                                }
                            </SelectValue>
                        </SelectTrigger>
                        <SelectContent>
                            {options.map((option) =>
                                'value' in option ? (
                                    <SelectItem key={option.value} value={option.value}>
                                        {option.label}
                                    </SelectItem>
                                ) : null
                            )}
                        </SelectContent>
                    </Select>
                )}
            </QuillSettingFormField>
            {expiresAt !== undefined && (
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    {expiresAt ? (
                        <>
                            <span>The key stops working on </span>
                            <TZLabel time={expiresAt} formatDate={EXPIRY_DATE_FORMAT} formatTime={EXPIRY_TIME_FORMAT} />
                            <span>.</span>
                        </>
                    ) : (
                        'The key keeps working until you delete it.'
                    )}
                </Text>
            )}
        </div>
    )
}
