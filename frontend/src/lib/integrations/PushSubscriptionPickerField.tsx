import { CyclotronJobInputSchemaType } from '~/types'

import { PushSubscriptionPicker } from './PushSubscriptionPicker'

export type PushSubscriptionPickerFieldProps = {
    schema: CyclotronJobInputSchemaType
    value?: string
    onChange?: (value: string | null) => void
}

export function PushSubscriptionPickerField({
    schema,
    value,
    onChange,
}: PushSubscriptionPickerFieldProps): JSX.Element {
    const platform = schema.platform as 'android' | 'ios' | 'web' | undefined
    return <PushSubscriptionPicker value={value} onChange={onChange} platform={platform} />
}
