import { Label } from 'lib/ui/Label/Label'

interface FlatNavSectionProps {
    label: string
    /** Optional small control rendered at the right edge of the section header. */
    action?: React.ReactNode
    children: React.ReactNode
}

export function FlatNavSection({ label, action, children }: FlatNavSectionProps): JSX.Element {
    return (
        <div className="flex flex-col gap-px mt-3">
            <div className="flex items-center justify-between pl-2 pr-1 min-h-5">
                <Label intent="menu" className="text-xxs text-secondary">
                    {label}
                </Label>
                {action}
            </div>
            {children}
        </div>
    )
}
