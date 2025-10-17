export function AISummaryMessage({ heading, subheading }: { heading: string; subheading: string }): JSX.Element {
    return (
        <div className="mb-2">
            <div>
                <h3 className="font-semibold mb-1">{heading}</h3>
                <div className="text-sm text-muted">{subheading}</div>
            </div>
        </div>
    )
}
