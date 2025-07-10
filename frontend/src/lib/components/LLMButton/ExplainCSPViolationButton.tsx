import { useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { useState } from 'react'

import { IconWarning } from '@posthog/icons'
import { Link, Popover, Spinner } from '@posthog/lemon-ui'

import api from 'lib/api'
import { SupportHeroHog } from 'lib/components/hedgehogs'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { SidePanelTab } from '~/types'

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
    const [result, setResult] = useState<JSX.Element | null>(null)
    const isMaxEnabled = useFeatureFlag('ARTIFICIAL_HOG')

    const { currentLocation } = useValues(router)

    const handleClick = async (): Promise<void> => {
        setIsOpen(true)

        if (!isMaxEnabled) {
            setResult(
                <div className="text-l flex min-h-40 flex-col items-center justify-center gap-4 text-center">
                    <SupportHeroHog style={{ maxWidth: 120, marginBottom: 8 }} />
                    <div>
                        Want to get CSP violation explanations from the cutest security hog in the world?
                        <br />
                        <Link
                            to={
                                combineUrl(currentLocation.pathname, currentLocation.search, {
                                    ...currentLocation.hashParams,
                                    panel: `${SidePanelTab.FeaturePreviews}:${FEATURE_FLAGS.ARTIFICIAL_HOG}`,
                                }).url
                            }
                        >
                            Enable Max AI
                        </Link>{' '}
                        in your feature previews.
                        <div className="mt-4">
                            <span className="text-muted text-xs">
                                Otherwise, you can edit this insight and remove this column on the SQL query.
                            </span>
                        </div>
                    </div>
                </div>
            )
            return
        }

        setLoading(true)
        try {
            const r = await api.cspReporting.explain(properties)
            if (r) {
                setResult(
                    <>
                        <LemonMarkdown wrapCode={true}>{r.response}</LemonMarkdown>
                        <div className="border-border-strong mt-2 flex items-center rounded border p-2">
                            <IconWarning className="text-warning-dark mr-2 flex-shrink-0" />
                            <span className="text-muted text-xs">
                                Security advice from robots should always be double-checked by humans
                            </span>
                        </div>
                    </>
                )
            } else {
                setResult(
                    <div className="text-l flex min-h-40 items-center justify-center gap-4">
                        Sorry! We failed to get a CSP explanation. Please try again later
                    </div>
                )
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
                <div className="min-w-160 max-w-200 max-h-160 min-h-40 p-4">
                    {loading ? (
                        <div className="flex min-h-40 items-center justify-center gap-4">
                            <div className="text-l">
                                <Spinner /> The security hogs are sniffing the violation{' '}
                            </div>
                        </div>
                    ) : (
                        result
                    )}
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
