import { IconX } from '@posthog/icons'
import { lemonToast, Popover, ProfilePicture } from '@posthog/lemon-ui'
import api from 'lib/api'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { useState } from 'react'

export type ExplainCSPViolationButtonProps = LemonButtonProps & {
    properties: Record<string, any>
    label: string
}

export const ExplainCSPViolationButton = ({
    properties,
    label,
    ...buttonProps
}: ExplainCSPViolationButtonProps): JSX.Element => {
    const [loading, setLoading] = useState(false)
    const [isOpen, setIsOpen] = useState(false)
    const [description, setDescription] = useState('')

    const handleClick = async (): Promise<void> => {
        setLoading(true)
        try {
            const r = await api.cspReporting.explain(properties)
            if (r) {
                setDescription(r.response)
                setIsOpen(true)
            } else {
                lemonToast.error('Failed to get CSP violation report explanation.')
            }
        } finally {
            setLoading(false)
        }
    }

    return (
        <Popover
            visible={isOpen}
            onClickOutside={() => setIsOpen(false)}
            overlay={
                <div className="p-4 max-w-160 max-h-160 overflow-auto">
                    <div className="flex items-center justify-between mb-2 border-b pb-2">
                        {/** We're not a MaxTool yet */}
                        <ProfilePicture
                            user={{ hedgehog_config: { use_as_profile: true } }}
                            size="md"
                            className="border bg-bg-light"
                        />
                        <h5 className="font-semibold m-0">CSP Violation Explanation</h5>
                        <LemonButton
                            type="tertiary"
                            onClick={() => setIsOpen(false)}
                            size="small"
                            icon={<IconX />}
                            className="ml-2"
                        />
                    </div>
                    <LemonMarkdown>{description}</LemonMarkdown>
                </div>
            }
        >
            {/* eslint-disable-next-line @typescript-eslint/no-misused-promises */}
            <LemonButton {...buttonProps} loading={loading} onClick={handleClick}>
                {label}
            </LemonButton>
        </Popover>
    )
}
