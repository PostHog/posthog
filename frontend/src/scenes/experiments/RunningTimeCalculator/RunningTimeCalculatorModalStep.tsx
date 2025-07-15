export const RunningTimeCalculatorModalStep = ({
    children,
    stepNumber,
    title,
    description,
}: {
    children: React.ReactNode
    stepNumber: number
    title: string
    description: string
}): JSX.Element => (
    <div className="space-y-6">
        <div className="rounded bg-light p-4 space-y-3">
            <div className="flex items-center gap-2">
                <span className="rounded-full bg-muted text-white w-6 h-6 flex items-center justify-center font-semibold">
                    {stepNumber}
                </span>
                <h4 className="font-semibold m-0">{title}</h4>
            </div>
            <p className="text-muted">{description}</p>
            <div className="space-y-2">{children}</div>
        </div>
    </div>
)
