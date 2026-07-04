import { useActions, useValues } from 'kea'
import React, { useState } from 'react'

import { IconCursorClick } from '@posthog/icons'
import { LemonButton, LemonSwitch, Tooltip } from '@posthog/lemon-ui'

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
    const { clickmapEnabled, matchLinksByHref, clickmapBoxes, totalClickCount } = useValues(logic)
    const { setClickmapEnabled, setMatchLinksByHref } = useActions(logic)

    return (
        <Popover
            overlay={
                <div className="p-2 w-80 deprecated-space-y-2">
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
                    <Tooltip title="Matching links by their target URL can exclude clicks from the heatmap if the URL is too unique.">
                        <LemonSwitch
                            checked={matchLinksByHref}
                            onChange={setMatchLinksByHref}
                            label="Match links by their target URL"
                            size="small"
                            fullWidth
                            bordered
                        />
                    </Tooltip>
                    {clickmapEnabled && clickmapBoxes.length > 0 ? (
                        <div className="text-xs text-muted">
                            Found: {clickmapBoxes.length} elements / {humanFriendlyLargeNumber(totalClickCount)} clicks
                        </div>
                    ) : null}
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
                tooltip="Clickmap settings"
                data-attr="clickmap-settings"
            >
                Clickmap settings
            </LemonButton>
        </Popover>
    )
}
