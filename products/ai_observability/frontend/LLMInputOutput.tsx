import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'

export function LLMInputOutput({
    inputDisplay,
    outputDisplay,
    inputHeading = 'Input',
    outputHeading = 'Output',
    bordered = false,
    inputButtons,
    outputButtons,
}: {
    inputDisplay: JSX.Element | JSX.Element[]
    outputDisplay: JSX.Element | JSX.Element[] | null
    inputHeading?: string
    outputHeading?: string
    bordered?: boolean
    inputButtons?: JSX.Element
    outputButtons?: JSX.Element
}): JSX.Element {
    return (
        <>
            <div className={bordered ? 'bg-surface-primary rounded-lg border p-2' : undefined}>
                <h4 className="flex items-center justify-between text-xs font-semibold mb-2">
                    <div className="flex items-center gap-x-1.5">
                        <IconArrowUp className="text-base" />
                        {inputHeading}
                    </div>
                    {inputButtons}
                </h4>
                {inputDisplay}
                {outputDisplay && (
                    <>
                        <h4 className="flex items-center justify-between text-xs font-semibold my-2">
                            <div className="flex items-center gap-x-1.5">
                                <IconArrowDown className="text-base" />
                                {outputHeading}
                            </div>
                            {outputButtons}
                        </h4>
                        {outputDisplay}
                    </>
                )}
            </div>
        </>
    )
}
