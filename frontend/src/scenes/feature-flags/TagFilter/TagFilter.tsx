import { useActions, useValues } from 'kea'
import * as React from 'react'
import { tagFilterLogic } from './tagFilterLogic'

export interface TagFilterProps {
    selectedTag?: string
}

// eslint-disable-next-line react/display-name
export const TagFilter = React.forwardRef<HTMLDivElement, TagFilterProps>(({ selectedTag }, ref): JSX.Element => {
    console.log(`selectedTag:`, selectedTag)

    const values = useValues(tagFilterLogic)
    const actions = useActions(tagFilterLogic)
    console.log(`values:`, values)
    console.log(`actions:`, actions)

    return (
        <div ref={ref}>
            TagFilter
            <pre>Hello</pre>
        </div>
    )
})
