import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'

export function SidePanelContentContainer({
    className,
    children,
}: {
    className?: string
    children?: React.ReactNode
}): JSX.Element {
    const isRemovingSidePanelFlag = useFeatureFlag('UX_REMOVE_SIDEPANEL')

    return (
        <div
            className={cn(
                'flex flex-col flex-1 overflow-y-auto p-3',
                {
                    // 3px is just enough to handle the focus within ring for sidepanel notebooks
                    'rounded mr-2 mb-2 ml-[3px] border border-primary': isRemovingSidePanelFlag,
                },
                className
            )}
        >
            {children}
        </div>
    )
}
