import { useState } from 'react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { ResizableBox } from 'react-resizable'
import 'react-resizable/css/styles.css'

export interface ResizeHeightProps {
    className?: string
    defaultHeight: number
    children: React.ReactNode | React.ReactNode[]
}
export function ResizeHeight({ defaultHeight, children, className }: ResizeHeightProps): JSX.Element {
    const [height, setHeight] = useState(defaultHeight)
    return (
        <AutoSizer disableHeight>
            {({ width }) => (
                <ResizableBox
                    width={width}
                    height={height}
                    onResizeStop={(_, { size }) => setHeight(size.height)}
                    resizeHandles={['s']}
                >
                    <div className={className}>{children}</div>
                </ResizableBox>
            )}
        </AutoSizer>
    )
}
