export function SurveyOptionsGroup({
    children,
    sectionTitle,
}: {
    children: React.ReactNode
    sectionTitle: string
}): JSX.Element {
    return (
        <div className="grid grid-cols-2 gap-x-2 gap-y-1 items-start">
            <h3 className="col-span-2 mb-0">{sectionTitle}</h3>
            {children}
        </div>
    )
}
