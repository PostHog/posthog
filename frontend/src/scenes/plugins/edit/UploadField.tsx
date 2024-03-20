import { LemonFileInput } from '@posthog/lemon-ui'

export function UploadField({ value, onChange }: { value?: File; onChange?: (file: File) => void }): JSX.Element {
    return (
        <>
            {value?.name ? <span>Selected file: {value.name}</span> : null}
            <LemonFileInput
                accept="*"
                multiple={false}
                onChange={(files) => onChange?.(files[0])}
                value={value?.size ? [value] : []}
                showUploadedFiles={false}
            />
        </>
    )
}
