import { Switch, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

export function QuillTabOptionSwitch({
    checked,
    onChange,
    label,
    tooltip,
    dataAttr,
}: {
    checked: boolean
    onChange: (checked: boolean) => void
    label: string
    tooltip: string
    dataAttr: string
}): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger render={<div className="flex w-fit items-center" />}>
                <Switch checked={checked} onCheckedChange={(next) => onChange(next)} data-attr={dataAttr}>
                    {label}
                </Switch>
            </TooltipTrigger>
            <TooltipContent side="left" className="max-w-80">
                {tooltip}
            </TooltipContent>
        </Tooltip>
    )
}
