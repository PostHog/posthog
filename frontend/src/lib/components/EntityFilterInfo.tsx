import { ActionFilter, EntityFilter, EntityTypes, FunnelStepRangeEntityFilter } from '~/types'
import { Typography } from 'antd'
import React from 'react'
import { TextProps } from 'antd/lib/typography/Text'
import { getKeyMapping } from 'lib/components/PropertyKeyInfo'
import { getDisplayNameFromEntityFilter } from 'scenes/insights/utils'

interface Props {
    filter: EntityFilter | ActionFilter | FunnelStepRangeEntityFilter
    showSubTitle?: boolean
    subTitles?: (string | number | null | undefined)[]
}

function TextWrapper(props: TextProps): JSX.Element {
    return (
        <Typography.Text style={{ maxWidth: 400 }} {...props}>
            {props.children}
        </Typography.Text>
    )
}

export function EntityFilterInfo({ filter, showSubTitle = true, subTitles }: Props): JSX.Element {
    const title = getDisplayNameFromEntityFilter(filter)
    const subtitle = subTitles ? subTitles.filter((s) => !!s).join(', ') : getDisplayNameFromEntityFilter(filter, false)

    if (filter.type === EntityTypes.NEW_ENTITY || (!title && !subtitle)) {
        return <TextWrapper title="Select filter">Select filter</TextWrapper>
    }

    const titleToDisplay = getKeyMapping(title, 'event')?.label?.trim() ?? title ?? undefined
    const subTitleToDisplay = getKeyMapping(subtitle, 'event')?.label?.trim() ?? subtitle ?? undefined

    return (
        <span style={{ display: 'flex', flexDirection: 'row', alignItems: 'center' }}>
            <TextWrapper ellipsis={false} title={titleToDisplay}>
                {titleToDisplay}
            </TextWrapper>
            {showSubTitle && titleToDisplay !== subTitleToDisplay && subTitleToDisplay && (
                <TextWrapper
                    ellipsis={true}
                    type="secondary"
                    style={{ fontSize: 13, marginLeft: 4 }}
                    title={subTitleToDisplay}
                >
                    ({subTitleToDisplay})
                </TextWrapper>
            )}
        </span>
    )
}
