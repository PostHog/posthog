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
    return <PushSubscriptionPicker value={value} onChange={onChange} platform={schema.platform} />
}
