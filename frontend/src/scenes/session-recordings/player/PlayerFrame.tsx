import React from 'react'

export const PlayerFrame = React.forwardRef<HTMLDivElement>(function PlayerFrameInner(props, ref): JSX.Element {
    return <div ref={ref}>Player Frame</div>
})
