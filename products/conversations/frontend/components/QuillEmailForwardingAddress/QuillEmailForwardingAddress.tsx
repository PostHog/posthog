import { IconCopy } from '@posthog/icons'
import { Button, Field, FieldDescription, FieldLabel, Text } from '@posthog/quill'

import { copyForwardingAddress } from '../EmailForwardingAddress/copyForwardingAddress'

export function QuillEmailForwardingAddress({ forwardingAddress }: { forwardingAddress: string }): JSX.Element {
    return (
        <Field>
            <FieldLabel>Forwarding address</FieldLabel>
            <FieldDescription>Forward incoming emails to this address in your email provider.</FieldDescription>
            <div className="flex items-center gap-2">
                <code data-quill className="break-all rounded-sm bg-muted px-2 py-1 text-xs">
                    {forwardingAddress}
                </code>
                <Button
                    variant="outline"
                    size="icon"
                    aria-label="Copy forwarding address"
                    tooltip="Copy forwarding address"
                    onClick={() => copyForwardingAddress(forwardingAddress)}
                >
                    <IconCopy />
                </Button>
            </div>
            <div className="flex flex-col gap-0.5">
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    <strong>Gmail:</strong> Settings → Forwarding → Add a forwarding address
                </Text>
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    <strong>Outlook:</strong> Settings → Mail → Forwarding → Enable forwarding
                </Text>
            </div>
        </Field>
    )
}
