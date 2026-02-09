import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'

export function SidePanelContentContainer({
    className,
    flagOffClassName,
    children,
}: {
    className?: string
    flagOffClassName?: string
    children?: React.ReactNode
}): JSX.Element {
    const isRemovingSidePanelFlag = useFeatureFlag('UX_REMOVE_SIDEPANEL')

    return (
        <div className={isRemovingSidePanelFlag ? 'h-full' : 'contents'}>
            <div
                className={cn(
                    !isRemovingSidePanelFlag && flagOffClassName,
                    // 3px is just enough to handle the focus within ring for sidepanel notebooks
                    isRemovingSidePanelFlag &&
                        // 'flex flex-col flex-1 overflow-y-auto p-3 rounded mr-2 mb-2 ml-[3px] focus-within:outline-none focus-within:ring-2 focus-within:ring-primary z-10',
                        'h-full p-2 bg-surface-primary flex flex-col flex-1 overflow-y-auto focus-within:outline-none focus-within:ring-2 focus-within:ring-primary z-10',
                    className
                )}
                data-attr={isRemovingSidePanelFlag ? 'side-panel-content' : undefined}
            >
                {children}
            </div>
        </div>
    )
}
