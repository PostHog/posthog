import { ActionFilter, EntityFilter } from '~/types'
import { Typography } from 'antd'
import { TextProps } from 'antd/lib/typography/Text'
import { getKeyMapping } from 'lib/taxonomy'
import { getDisplayNameFromEntityFilter, isAllEventsEntityFilter } from 'scenes/insights/utils'

interface EntityFilterInfoProps {
    filter: EntityFilter | ActionFilter
    allowWrap?: boolean
    showSingleName?: boolean
    style?: React.CSSProperties
}

function TextWrapper(props: TextProps): JSX.Element {
    return (
        <Typography.Text style={{ maxWidth: 400 }} {...props}>
            {props.children}
        </Typography.Text>
    )
}

export function EntityFilterInfo({
    filter,
    allowWrap = false,
    showSingleName = false,
    style,
}: EntityFilterInfoProps): JSX.Element {
    if (isAllEventsEntityFilter(filter)) {
        return (
            <TextWrapper title="All events" className="text-muted-alt">
                All events
            </TextWrapper>
        )
    }

    const title = getDisplayNameFromEntityFilter(filter, false)
    const titleToDisplay = getKeyMapping(title, 'event')?.label?.trim() ?? title ?? undefined

    // No custom name
    if (!filter?.custom_name) {
        return (
            // eslint-disable-next-line react/forbid-dom-props
            <span className="flex items-center" style={style}>
                <TextWrapper ellipsis={!allowWrap} title={titleToDisplay}>
                    {titleToDisplay}
                </TextWrapper>
            </span>
        )
    }

    // Display custom name first and action title as secondary
    const customTitle = getDisplayNameFromEntityFilter(filter, true)

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <span className="flex items-center" style={style}>
            <TextWrapper ellipsis={!allowWrap} title={customTitle ?? undefined}>
                {customTitle}
            </TextWrapper>
            {!showSingleName && (
                <TextWrapper ellipsis={!allowWrap} type="secondary" className="ml-1" title={titleToDisplay}>
                    ({titleToDisplay})
                </TextWrapper>
            )}
        </span>
    )
}
