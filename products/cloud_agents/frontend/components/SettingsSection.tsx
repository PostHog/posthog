/** One titled section of the settings page. */
export function SettingsSection({
    title,
    description,
    children,
    'data-attr': dataAttr,
}: {
    title: string
    description?: React.ReactNode
    children: React.ReactNode
    'data-attr'?: string
}): JSX.Element {
    return (
        <section className="flex min-w-0 flex-col gap-3 border-b pb-6 last:border-b-0" data-attr={dataAttr}>
            <div>
                <h2 className="m-0 text-lg font-semibold">{title}</h2>
                {description ? <p className="m-0 text-secondary max-w-180">{description}</p> : null}
            </div>
            {children}
        </section>
    )
}
