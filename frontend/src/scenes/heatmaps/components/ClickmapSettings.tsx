import { useActions, useValues } from 'kea'
import React, { useState } from 'react'

import { IconCursorClick } from '@posthog/icons'
import { LemonButton, LemonSwitch, Spinner, Tooltip } from '@posthog/lemon-ui'

import { Popover } from 'lib/lemon-ui/Popover'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import { recordingClickmapLogic } from './recordingClickmapLogic'

export function ClickmapSettings({
    iframeRef,
}: {
    iframeRef?: React.MutableRefObject<HTMLIFrameElement | null>
}): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)
    const logic = recordingClickmapLogic({ iframeRef })
    const { clickmapEnabled, matchLinksByHref, clickmapBoxes, totalClickCount, elementStatsLoading, elementStats } =
        useValues(logic)
    const { setClickmapEnabled, setMatchLinksByHref } = useActions(logic)

    const elementWord = clickmapBoxes.length === 1 ? 'element' : 'elements'
    const clickWord = totalClickCount === 1 ? 'click' : 'clicks'

    return (
        <Popover
            overlay={
                <div className="p-2 w-80 flex flex-col gap-2">
                    <LemonSwitch
                        checked={clickmapEnabled}
                        onChange={setClickmapEnabled}
                        label="Show clickmap"
                        size="small"
                        fullWidth
                        bordered
                    />
                    <div className="text-xs text-muted">
                        Overlay click counts on the elements users actually clicked.
                    </div>
                    <Tooltip title="Links whose target URL differs per user (e.g. contains IDs) may not match any element in the snapshot.">
                        <LemonSwitch
                            checked={matchLinksByHref}
                            onChange={setMatchLinksByHref}
                            label="Match links by their target URL"
                            size="small"
                            fullWidth
                            bordered
                        />
                    </Tooltip>
                    {clickmapEnabled && (
                        <div className="text-xs text-muted flex items-center gap-1">
                            {elementStatsLoading ? (
                                <>
                                    <Spinner /> Loading...
                                </>
                            ) : elementStats !== null && clickmapBoxes.length === 0 ? (
                                'No elements matched.'
                            ) : elementStats !== null ? (
                                <>
                                    Found: {clickmapBoxes.length} {elementWord} /{' '}
                                    {humanFriendlyLargeNumber(totalClickCount)} {clickWord}
                                </>
                            ) : null}
                        </div>
                    )}
                </div>
            }
            visible={isOpen}
            onClickOutside={() => setIsOpen(false)}
            placement="bottom"
        >
            <LemonButton
                type="secondary"
                size="small"
                onClick={() => setIsOpen(!isOpen)}
                icon={<IconCursorClick />}
                data-attr="clickmap-settings"
            >
                Clickmap settings
            </LemonButton>
        </Popover>
    )
}
