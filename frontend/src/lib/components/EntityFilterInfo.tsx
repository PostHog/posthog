import { ActionFilter, EntityFilter, EntityTypes, FunnelStepRangeEntityFilter } from '~/types'
import { Typography } from 'antd'
import React from 'react'
import { TextProps } from 'antd/es/typography/Text'
import { getKeyMapping } from 'lib/components/PropertyKeyInfo'
import { getDisplayNameFromEntityFilter } from 'scenes/insights/utils'

interface Props {
    filter: EntityFilter | ActionFilter | FunnelStepRangeEntityFilter
    showSubTitle?: boolean
}

function TextWrapper(props: TextProps): JSX.Element {
    return (
        <Typography.Text ellipsis={true} style={{ maxWidth: 400 }} {...props}>
            {props.children}
        </Typography.Text>
    )
}

export function EntityFilterInfo({ filter, showSubTitle = true }: Props): JSX.Element {
    const title = getDisplayNameFromEntityFilter(filter)
    const subtitle = getDisplayNameFromEntityFilter(filter, false)

    if (filter.type === EntityTypes.NEW_ENTITY || (!title && !subtitle)) {
        return <TextWrapper title="Select filter">Select filter</TextWrapper>
    }

    const titleToDisplay = getKeyMapping(title, 'event')?.label ?? title ?? undefined
    const subTitleToDisplay = getKeyMapping(subtitle, 'event')?.label ?? subtitle ?? undefined

    return (
        <span style={{ display: 'flex', flexDirection: 'row', alignItems: 'center' }}>
            <TextWrapper title={titleToDisplay}>{titleToDisplay}</TextWrapper>
            {showSubTitle && title !== subtitle && (
                <TextWrapper type="secondary" style={{ fontSize: 13, marginLeft: 4 }} title={subTitleToDisplay}>
                    ({subTitleToDisplay})
                </TextWrapper>
            )}
        </span>
    )
}
