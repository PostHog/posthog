import { IconUpload } from '@posthog/icons'
import { Button } from '@posthog/quill'

export function QuillUploadButton({
    label,
    disabledReason,
}: {
    label: string
    disabledReason: string | null | undefined
}): JSX.Element {
    return (
        <Button disabledReason={disabledReason}>
            <IconUpload />
            {label}
        </Button>
    )
}
