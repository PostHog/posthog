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
        <div className="bg-light space-y-3 rounded p-4">
            <div className="flex items-center gap-2">
                <span className="bg-muted flex h-6 w-6 items-center justify-center rounded-full font-semibold text-white">
                    {stepNumber}
                </span>
                <h4 className="m-0 font-semibold">{title}</h4>
            </div>
            <p className="text-muted">{description}</p>
            <div className="space-y-2">{children}</div>
        </div>
    </div>
)
