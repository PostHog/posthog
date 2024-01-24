import { LemonButton, LemonFileInput } from '@posthog/lemon-ui'
import { IconUploadFile } from 'lib/lemon-ui/icons'

export function UploadField({ value, onChange }: { value?: File; onChange?: (file: File) => void }): JSX.Element {
    return (
        <LemonFileInput
            accept={'image/*'}
            multiple={false}
            onChange={(files) => onChange?.(files[0])}
            value={value?.size ? [value] : []}
            showUploadedFiles={false}
            callToAction={
                <LemonButton className="ph-ignore-input" icon={<IconUploadFile />}>
                    Click to upload
                </LemonButton>
            }
        />
    )
}
