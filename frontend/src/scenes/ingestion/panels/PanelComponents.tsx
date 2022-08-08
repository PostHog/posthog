import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { IconChevronRight } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonDivider } from 'lib/components/LemonDivider'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import React from 'react'
import { BOOKMARKLET } from '../constants'
import { ingestionLogic } from '../ingestionLogic'
import './Panels.scss'

export function PanelFooter(): JSX.Element {
    const { platform } = useValues(ingestionLogic)
    const { setPlatform, setVerify } = useActions(ingestionLogic)
    const { reportIngestionTryWithBookmarkletClicked } = useActions(eventUsageLogic)

    return (
        <div className="panel-footer">
            <LemonDivider thick dashed style={{ marginTop: 24, marginBottom: 24 }} />
            {platform === BOOKMARKLET ? (
                <div>
                    <LemonButton
                        type="primary"
                        size="large"
                        fullWidth
                        center
                        onClick={() => {
                            reportIngestionTryWithBookmarkletClicked()
                            setVerify(true)
                        }}
                    >
                        Try PostHog with the exploration bookmarklet
                    </LemonButton>
                    <LemonButton
                        className="mt-2"
                        size="large"
                        fullWidth
                        center
                        type="secondary"
                        onClick={() => setPlatform(null)}
                    >
                        Back to setup
                    </LemonButton>
                </div>
            ) : (
                <div>
                    <LemonButton
                        type="primary"
                        size="large"
                        fullWidth
                        center
                        className="mb-2"
                        onClick={() => setVerify(true)}
                    >
                        Continue
                    </LemonButton>
                    <LemonButton
                        className="mt-2"
                        size="large"
                        fullWidth
                        center
                        type="secondary"
                        onClick={() => setVerify(true)}
                    >
                        Skip for now
                    </LemonButton>
                </div>
            )}
        </div>
    )
}

export function PanelHeader({ index }: { index: number }): JSX.Element {
    return (
        <div className="flex items-center text-muted">
            <span className={clsx({ 'font-medium': index === 1 })}>Step 1</span>
            {index > 1 && (
                <>
                    <IconChevronRight />
                    <span className={clsx({ 'font-medium': index === 2 })}>Step 2</span>
                </>
            )}
            {index > 2 && (
                <>
                    <IconChevronRight />
                    <span className={clsx({ 'font-medium': index === 3 })}>Step 3</span>
                </>
            )}
        </div>
    )
}
