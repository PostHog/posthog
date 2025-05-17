import { IconX } from '@posthog/icons'
import { Popover, ProfilePicture, Spinner } from '@posthog/lemon-ui'
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
    const [result, setResult] = useState({})

    const handleClick = async (): Promise<void> => {
        setLoading(true)
        setIsOpen(true)
        try {
            const r = await api.cspReporting.explain(properties)
            if (r) {
                setResult(<LemonMarkdown>{r.response}</LemonMarkdown>)
            } else {
                setResult(<div className="flex items-center justify-center min-h-40 gap-4 text-l">
                    Sorry! We failed to get a CSP explanation. Please try again later
            </div>)
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
                <div className="p-4 min-w-140 max-w-140 min-h-40 max-h-80 overflow-auto">
                    <div className="flex items-center justify-between mb-2 border-b pb-2">
                        {/** We're not a MaxTool... yet */}
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

                    {loading ?
                        <div className="flex items-center justify-center min-h-40 gap-4">
                            <div className="text-l"><Spinner /> Thinking about security sheeps </div>
                        </div> : result}
                </div>
            }
        >
            {/* eslint-disable-next-line @typescript-eslint/no-misused-promises */}
            <LemonButton {...buttonProps} onClick={handleClick}>
                {label}
            </LemonButton>
        </Popover>
    )
}
