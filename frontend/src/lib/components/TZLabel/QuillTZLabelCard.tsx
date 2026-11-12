import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconGear } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { shortTimeZone } from 'lib/utils/timezones'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { QuillTZLabelRow } from './QuillTZLabelRow'
import { getTimezoneRows } from './timezoneRows'

interface QuillTZLabelCardProps {
    time: dayjs.Dayjs
    showSeconds?: boolean
    title?: string
    displayTimezone?: string
}

/** The same moment in each timezone, each one copyable. It mounts each time the card opens. */
export function QuillTZLabelCard({ time, showSeconds, title, displayTimezone }: QuillTZLabelCardProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { reportTimezoneComponentViewed } = useActions(eventUsageLogic)

    useEffect(() => {
        reportTimezoneComponentViewed('label', currentTeam?.timezone, shortTimeZone())
    }, []) // oxlint-disable-line react-hooks/exhaustive-deps

    return (
        <div className="flex flex-col">
            <div className="flex items-center justify-between gap-2 border-b border-border py-1 ps-3 pe-1">
                <Text size="sm" weight="semibold" render={<h4 className="m-0" />}>
                    {title || 'Timezone conversion'}
                </Text>
                <Button
                    size="icon-sm"
                    tooltip="Date and time settings"
                    aria-label="Date and time settings"
                    render={<LinkPrimitive to={urls.settings('environment-customization', 'date-and-time')} />}
                    data-attr="tz-label-settings"
                >
                    <IconGear />
                </Button>
            </div>
            <div className="flex flex-col gap-px p-1">
                {getTimezoneRows(time, { showSeconds, displayTimezone, projectTimezone: currentTeam?.timezone }).map(
                    (row) => (
                        <QuillTZLabelRow key={row.key} row={row} />
                    )
                )}
            </div>
        </div>
    )
}
